"""Web search tool — OpenAI Responses API `web_search` backend (Feature 2).

The active, sole web search implementation behind the Tool interface (see
tools/base.py) — see docs/architecture.md's decision log for why (an
earlier Tavily-backed implementation was tried and then fully removed).
Uses OPENAI_API_KEY only.

IMPORTANT — read before treating `content` below as raw retrieved text:
OpenAI's built-in web_search tool does NOT return a list of independent raw
search results the way a typical search API does. One Responses API call
with `tools=[{"type": "web_search"}]` performs search AND synthesis
together in a single model pass, returning one model-authored answer with
inline `url_citation` annotations marking which source backs which span of
text.

This adapter derives {title, url, content} entries from those citations:
- Each entry is a genuinely distinct cited source, deduplicated by URL —
  NOT one result duplicated to fill the shape. If OpenAI cites 3 different
  pages, this returns 3 entries; if it cites only 1, this returns 1,
  honestly (it does not pad or split to manufacture more entries).
- BUT each entry's `content` is the substring of OpenAI's own synthesized
  answer that the citation's annotation covers (start_index:end_index) —
  NOT raw content scraped from that source page. The grader therefore ends
  up judging an already-synthesized excerpt written by the search model,
  not the source's actual retrieved text. No code in grader.py needs to
  change (the interface is identical), but what it's grading is
  semantically different from a raw-result search API — flagged explicitly
  here rather than treated as equivalent.
"""

from typing import Any

from openai import AsyncOpenAI

from app.cache.redis_client import RETRIEVAL_TTL_SECONDS, get_cached, hash_key, set_cached
from app.core.config import Settings, get_settings
from app.tools.base import Tool

_client: AsyncOpenAI | None = None


def _get_client(settings: Settings) -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


def _extract_cited_sources(response: Any) -> list[dict[str, Any]]:
    """Pull distinct {title, url, content} entries out of a Responses API
    result that used the web_search tool. See module docstring for what
    `content` actually is here (a synthesized excerpt, not raw page text)."""
    seen_urls: set[str] = set()
    results: list[dict[str, Any]] = []

    for item in getattr(response, "output", None) or []:
        if getattr(item, "type", None) != "message":
            continue
        for content_part in getattr(item, "content", None) or []:
            text = getattr(content_part, "text", "") or ""
            annotations = getattr(content_part, "annotations", None) or []
            for ann in annotations:
                if getattr(ann, "type", None) != "url_citation":
                    continue
                url = getattr(ann, "url", None)
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                start = getattr(ann, "start_index", 0) or 0
                end = getattr(ann, "end_index", len(text)) or len(text)
                results.append(
                    {
                        "title": getattr(ann, "title", "") or "",
                        "url": url,
                        "content": text[start:end],
                    }
                )

    return results


class OpenAIWebSearchTool(Tool):
    name = "web_search_openai"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def run(self, input: str) -> list[dict[str, Any]]:
        # retrieval:{query_hash} — cache-first, per Feature 3's spec. A miss
        # or any Redis failure both just fall through to the live call;
        # get_cached()/set_cached() never raise (docs/constraints.md).
        cache_key = f"retrieval:{hash_key(input, self._settings.openai_model)}"
        cached = await get_cached(cache_key, settings=self._settings)
        if cached is not None:
            return cached

        client = _get_client(self._settings)
        response = await client.responses.create(
            model=self._settings.openai_model,
            input=input,
            tools=[{"type": "web_search"}],
            # Forces this specific tool rather than leaving it optional
            # (the prior default: tool_choice omitted = "auto", model free
            # to skip search and answer from its own knowledge instead).
            # Confirmed empirically against the live API — the installed
            # SDK's ToolChoiceTypesParam type stub only lists
            # "web_search_preview" as forceable, not "web_search", but
            # that's a stale/incomplete type; the real API accepts this.
            # Root cause + eval-measured baseline this addresses: see
            # docs/architecture.md's "Web search tool" decision log row.
            tool_choice={"type": "web_search"},
        )
        results = _extract_cited_sources(response)

        await set_cached(cache_key, results, RETRIEVAL_TTL_SECONDS, settings=self._settings)
        return results

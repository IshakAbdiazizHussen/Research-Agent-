"""Shared LLM client (Feature 2: Core Research Agent Graph).

Not listed in docs/architecture.md's backend/ tree — added because all three
LLM-calling nodes (grader, rewriter, synthesizer) need the same thin wrapper
around the OpenAI client, and each instantiating its own client would defeat
the point of centralizing config (docs/architecture.md's core/config.py).
Worth folding into architecture.md's tree if this pattern sticks, same as
core/deps.py was after Feature 1.

Feature 3 (Retrieval & LLM Result Caching) wraps `complete()` itself, here,
rather than separately in grader.py/rewriter.py/synthesizer.py — this is
the one place every LLM call from all three nodes actually goes through,
so it's the correct place to cache once instead of three times (matches
this feature's own Guidelines: TTLs/keys defined once, not re-typed per
call site). No node needed to change.
"""

from openai import AsyncOpenAI

from app.cache.redis_client import LLM_TTL_SECONDS, get_cached, hash_key, set_cached
from app.core.config import Settings, get_settings

_client: AsyncOpenAI | None = None


def _get_client(settings: Settings) -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


async def complete(
    system_prompt: str,
    user_prompt: str,
    *,
    settings: Settings | None = None,
) -> str:
    """Run one system+user prompt through the configured OpenAI model
    (settings.openai_model — never hardcoded in a node) and return the plain
    text completion. Cache-first: llm:{prompt_hash} (docs/constraints.md)."""
    settings = settings or get_settings()

    cache_key = f"llm:{hash_key(settings.openai_model, system_prompt, user_prompt)}"
    cached = await get_cached(cache_key, settings=settings)
    if cached is not None:
        return cached

    client = _get_client(settings)
    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    result = (response.choices[0].message.content or "").strip()

    await set_cached(cache_key, result, LLM_TTL_SECONDS, settings=settings)
    return result

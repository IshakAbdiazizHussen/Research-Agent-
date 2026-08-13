"""Synthesizer node (Feature 2: Core Research Agent Graph).

Runs once retrieval is sufficient or the retry cap is reached. Prompt text
is verbatim from docs/development_plan.md — do not edit it here without
updating that doc.
"""

from app.agent.llm_client import complete
from app.agent.state import AgentState, GradedDoc, Source

_SYSTEM_PROMPT = """You are a research assistant. Using ONLY the provided sources,
write a clear, accurate answer to the user's question. Cite sources inline
using [1], [2], etc. matching the numbered source list. If the sources are
insufficient to fully answer the question, say so explicitly rather than
filling gaps from prior knowledge. Never state a claim that isn't
supported by at least one provided source."""

_USER_PROMPT_TEMPLATE = """Question: {query}

Sources:
{numbered_sources}

Write the answer now, with inline citations."""


def _select_sources(graded_docs: list[GradedDoc]) -> list[GradedDoc]:
    relevant = [doc for doc in graded_docs if doc["relevant"]]
    # Fall back to whatever was found so the prompt's own "say so explicitly
    # if insufficient" instruction can kick in, rather than synthesizing
    # from zero sources.
    return relevant or graded_docs


def _format_numbered_sources(docs: list[GradedDoc]) -> str:
    if not docs:
        return "(no sources found)"
    return "\n\n".join(
        f"[{i}] {doc['title']} ({doc['url']})\n{doc['content']}"
        for i, doc in enumerate(docs, start=1)
    )


async def synthesizer_node(state: AgentState) -> dict:
    selected = _select_sources(state["graded_docs"])
    numbered_sources = _format_numbered_sources(selected)

    user_prompt = _USER_PROMPT_TEMPLATE.format(
        query=state["query"], numbered_sources=numbered_sources
    )
    answer = await complete(_SYSTEM_PROMPT, user_prompt)

    sources: list[Source] = [
        {"url": doc["url"], "title": doc["title"], "snippet": doc["content"]}
        for doc in selected
    ]

    return {
        "answer": answer,
        "sources": sources,
        "status": "completed",
    }

"""Grader node (Feature 2: Core Research Agent Graph).

Runs the grader prompt once per retrieved document, concurrently, and tags
each with a relevance judgement. Prompt text is verbatim from
docs/development_plan.md — do not edit it here without updating that doc.
"""

import asyncio

from app.agent.llm_client import complete
from app.agent.state import AgentState, GradedDoc

_SYSTEM_PROMPT = """You are grading whether a retrieved web document is relevant and
useful for answering a research question. Be strict: only mark a document
relevant if it would materially help answer the question, not merely
mention related keywords."""

_USER_PROMPT_TEMPLATE = """Question: {query}

Retrieved document (title, url, snippet):
{document}

Respond with only one word: "relevant" or "irrelevant"."""


async def _grade_one(query: str, doc: dict) -> GradedDoc:
    document_text = f"{doc['title']}\n{doc['url']}\n{doc['content']}"
    user_prompt = _USER_PROMPT_TEMPLATE.format(query=query, document=document_text)
    verdict = await complete(_SYSTEM_PROMPT, user_prompt)
    relevant = verdict.strip().lower().startswith("relevant")
    return {**doc, "relevant": relevant}


async def grader_node(state: AgentState) -> dict:
    graded = await asyncio.gather(
        *(_grade_one(state["query"], doc) for doc in state["retrieved_docs"])
    )

    return {
        "graded_docs": list(graded),
        "status": "grading",
    }

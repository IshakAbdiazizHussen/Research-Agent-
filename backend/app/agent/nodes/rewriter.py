"""Rewriter node (Feature 2: Core Research Agent Graph).

Runs when the grader finds the current result set insufficient. Prompt text
is verbatim from docs/development_plan.md — do not edit it here without
updating that doc.

Only increments retry_count; the retry *cap* (3, per docs/constraints.md)
is enforced by the conditional edge in agent/graph.py, not here — this node
has no opinion on when to stop, only on how to rewrite.
"""

from app.agent.llm_client import complete
from app.agent.state import AgentState

_SYSTEM_PROMPT = """You rewrite research questions into better web search queries. The
previous search did not return enough relevant results. Produce a single
improved search query that is more specific, uses better search terms, or
approaches the question from a different angle. Do not answer the
question — only output the improved query."""

_USER_PROMPT_TEMPLATE = """Original question: {query}
Previous search query: {previous_search_query}
Number of relevant documents found: {relevant_count}

Improved search query:"""


async def rewriter_node(state: AgentState) -> dict:
    relevant_count = sum(1 for doc in state["graded_docs"] if doc["relevant"])
    user_prompt = _USER_PROMPT_TEMPLATE.format(
        query=state["query"],
        previous_search_query=state["search_query"],
        relevant_count=relevant_count,
    )
    new_search_query = await complete(_SYSTEM_PROMPT, user_prompt)

    return {
        "search_query": new_search_query.strip(),
        "retry_count": state["retry_count"] + 1,
        "status": "rewriting",
    }

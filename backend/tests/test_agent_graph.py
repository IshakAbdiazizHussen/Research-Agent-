"""Feature 2 (Core Research Agent Graph) tests.

Runs the graph directly (no HTTP), per docs/development_plan.md's QA
section, against a handful of hand-picked queries. These make real OpenAI
calls (chat completions + the web_search tool) — no mocking — so expect
network dependency and real API cost per run (see docs/constraints.md cost
ceilings).
"""

import pytest

from app.agent.graph import MAX_RETRIES, run_research

QUESTIONS = [
    "What is the capital of France?",
    "What are the current best practices for structuring a FastAPI project?",
]


@pytest.mark.parametrize("query", QUESTIONS)
async def test_graph_produces_cited_answer(query):
    final_state = await run_research(query)

    assert final_state["answer"], "graph must produce a non-empty answer"
    assert final_state["sources"], "graph must attach at least one source"
    assert final_state["retry_count"] <= MAX_RETRIES
    assert final_state["status"] == "completed"

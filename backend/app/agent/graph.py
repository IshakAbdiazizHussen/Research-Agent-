"""LangGraph StateGraph wiring (Feature 2: Core Research Agent Graph; Postgres
checkpointer wired in by Feature 4).

retrieve -> grade -> (enough relevant docs? synthesize : rewrite -> retrieve,
bounded) -> synthesize.
"""

from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agent.nodes.grader import grader_node
from app.agent.nodes.retriever import retriever_node
from app.agent.nodes.rewriter import rewriter_node
from app.agent.nodes.synthesizer import synthesizer_node
from app.agent.state import AgentState

# Hard-coded per docs/constraints.md ("LangGraph retry/loop caps") — changing
# this number is a sign-off item, not a routine tuning knob. Defined once
# here (not re-typed in any node) per Feature 2's Guidelines.
MAX_RETRIES = 3

# How many graded-relevant docs count as "enough" to synthesize from. Not
# specified anywhere in docs/ — a starting default in the same spirit as
# project_definition.md's other starting thresholds; tune once real eval
# data exists.
MIN_RELEVANT_DOCS = 2


def _route_after_grading(state: AgentState) -> str:
    relevant_count = sum(1 for doc in state["graded_docs"] if doc["relevant"])
    if relevant_count >= MIN_RELEVANT_DOCS:
        return "synthesizer"
    if state["retry_count"] >= MAX_RETRIES:
        return "synthesizer"
    return "rewriter"


def build_graph(checkpointer: Any = None):
    """checkpointer=None (default): ephemeral, in-memory run — used by
    tests/test_agent_graph.py and the Feature 2/3 throwaway dev endpoint.
    Feature 4's real API route passes a connected AsyncPostgresSaver (see
    agent/checkpointer.py) so runs survive a process restart."""
    graph = StateGraph(AgentState)

    graph.add_node("retriever", retriever_node)
    graph.add_node("grader", grader_node)
    graph.add_node("rewriter", rewriter_node)
    graph.add_node("synthesizer", synthesizer_node)

    graph.add_edge(START, "retriever")
    graph.add_edge("retriever", "grader")
    graph.add_conditional_edges(
        "grader",
        _route_after_grading,
        {"synthesizer": "synthesizer", "rewriter": "rewriter"},
    )
    graph.add_edge("rewriter", "retriever")
    graph.add_edge("synthesizer", END)

    return graph.compile(checkpointer=checkpointer)


def initial_state(query: str) -> AgentState:
    """The AgentState every new run/thread starts from — shared by
    run_research() below and Feature 4's API route so the two never drift."""
    return {
        "query": query,
        "search_query": "",
        "retrieved_docs": [],
        "graded_docs": [],
        "retry_count": 0,
        "answer": None,
        "sources": [],
        "status": "pending",
    }


async def run_research(query: str) -> AgentState:
    """Convenience entrypoint: build an ephemeral (no checkpointer) graph and
    run it end-to-end for one query. Used by tests/test_agent_graph.py and
    the Feature 2/3 throwaway /dev/test-research endpoint — not by Feature
    4's real API route, which needs the checkpointed graph instead."""
    app = build_graph()
    return await app.ainvoke(initial_state(query))

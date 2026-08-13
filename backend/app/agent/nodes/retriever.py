"""Retriever node (Feature 2: Core Research Agent Graph).

Calls the web search tool exclusively through tools/base.py's interface
(docs/development_plan.md, Feature 2 Guidelines) — never a raw HTTP call
inlined here.

Note: docs/architecture.md's backend/ tree comment on this file currently
reads "calls memory.search()" — that describes Feature 5 (long-term
memory), not yet built. Until Feature 5 lands, this node only calls the web
search tool, per Feature 2's own spec in docs/development_plan.md.

Active tool registration: OpenAIWebSearchTool (tools/web_search_openai.py).
An earlier Tavily-backed implementation (tools/web_search.py) was tried
first, then fully removed — Tavily's site was unreliably reachable from
this network, and OpenAI's built-in web_search tool works through the
OPENAI_API_KEY already funded for the LLM calls, so no second provider/key
was needed. See docs/architecture.md's decision log for the full record.
A future alternate search backend would only require a new class behind
the Tool interface (tools/base.py) and swapping the import/instantiation
here — no other file would need to change.
"""

from app.agent.state import AgentState
from app.tools.web_search_openai import OpenAIWebSearchTool


async def retriever_node(state: AgentState) -> dict:
    search_query = state.get("search_query") or state["query"]

    tool = OpenAIWebSearchTool()
    results = await tool.run(search_query)

    return {
        "search_query": search_query,
        "retrieved_docs": results,
        "status": "retrieving",
    }

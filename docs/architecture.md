# Architecture

## System diagram

```
Frontend (Next.js/React)
   -> HTTP request + SSE stream for progress
Backend (FastAPI)
   -> invokes LangGraph orchestrator
LangGraph orchestrator
   -> Tools layer (retrieval, search, external APIs)
   -> Memory layer (short-term run state, long-term knowledge store)
Database layer
   -> Postgres, accessed via Prisma — users, runs, LangGraph checkpoints
   -> Redis — cache layer for retrieval/LLM results
   -> Vector store (swappable, behind an interface) — for long-term memory
```

This maps directly to the problem breakdown in `project_definition.md`:
the LangGraph orchestrator implements the retrieve → grade → rewrite/retry
→ synthesize loop (Step 6); the Tools layer holds the web-search tool
(Step 6, in-scope); the Memory layer's long-term store holds a customer's
past runs (Step 4); Redis exists to cut duplicate cost/latency (Step 5);
Postgres/Prisma persists runs so they're revisitable (Step 3); the FastAPI
SSE stream is what makes progress visible to the customer (Step 3).

## Folder trees

```
backend/
├── app/
│   ├── main.py                  # FastAPI app entrypoint, mounts routes
│   ├── api/
│   │   └── routes/
│   │       └── research.py      # POST /research, GET /research/{id}/stream (SSE)
│   ├── agent/
│   │   ├── graph.py             # LangGraph StateGraph definition (nodes + edges)
│   │   ├── state.py             # TypedDict/Pydantic schema for graph state
│   │   └── nodes/
│   │       ├── retriever.py     # calls memory.search()
│   │       ├── grader.py        # "is context sufficient?" LLM call
│   │       ├── rewriter.py      # reformulates query on insufficient context
│   │       └── synthesizer.py   # final answer generation
│   ├── tools/
│   │   ├── base.py              # Tool interface/protocol
│   │   ├── web_search_openai.py # OpenAI Responses API web_search backend (active default)
│   │   └── retriever_tool.py    # wraps memory.search() as a callable tool
│   ├── memory/
│   │   ├── base.py              # abstract store()/search() interface — the swappable one
│   │   ├── in_memory_store.py   # dev/prototype backend
│   │   ├── pgvector_store.py    # Postgres + pgvector backend
│   │   └── qdrant_store.py      # only added when you actually need it
│   ├── cache/
│   │   └── redis_client.py      # Redis connection + get_cached()/set_cached() interface;
│   │                             # callers never touch the raw Redis client directly
│   ├── db/
│   │   ├── prisma/
│   │   │   └── schema.prisma    # Prisma schema: User, ResearchRun, Message, Checkpoint models
│   │   └── prisma_client.py     # Prisma Client Python instance/session setup
│   └── core/
│       ├── config.py            # env vars, settings
│       ├── logging.py           # observability/tracing setup
│       └── deps.py              # dev-only current-user resolution stand-in (Feature 1)
├── tests/
│   ├── test_agent_graph.py      # test the graph directly, no HTTP needed
│   └── eval/
│       └── eval_set.json        # Q/A pairs for retrieval/answer evaluation
├── requirements.txt or pyproject.toml
└── .env
```

```
frontend/
├── app/                          # Next.js app router
│   ├── page.tsx                  # main chat/research UI
│   └── layout.tsx
├── components/
│   ├── chat/
│   │   ├── MessageList.tsx
│   │   ├── QueryInput.tsx
│   │   └── StreamingStatus.tsx   # shows "retrieving...", "synthesizing..." from SSE
│   └── ui/                       # generic buttons, cards, etc.
├── lib/
│   ├── api.ts                    # fetch wrapper for /research endpoint
│   └── sse.ts                    # EventSource handling for streaming
├── types/
│   └── research.ts               # shared types matching backend's response schema
├── package.json
└── .env.local
```

```
Postgres tables (defined via prisma/schema.prisma, not raw SQL):
├── User               # id, email, createdAt, etc.
├── ResearchRun         # id, userId, query, status, createdAt
├── Message             # id, runId, role, content, stepType, sequence, createdAt
│                        # stepType (e.g. "retrieving"/"grading"/"synthesizing") drives
│                        # StreamingStatus.tsx; sequence + createdAt order the transcript
└── Checkpoint           # LangGraph's checkpoint state, written by its Postgres checkpointer
```

```
Redis keys (cache layer, not persistent storage):
├── retrieval:{query_hash}    # cached retrieval results, TTL defined in constraints.md
├── llm:{prompt_hash}          # cached LLM/synthesis output, TTL defined in constraints.md
└── run:{run_id}:status         # in-flight run status for SSE reconnects, TTL defined in constraints.md
```

```
Vector store (undecided — in-memory / pgvector / Qdrant):
└── documents_collection      # vector + payload {source, doc_id, section, date} — schema
                                # finalized only once a backend is chosen per the decision log
```

## Decision log

| Decision | Choice | Why | Revisit when |
|---|---|---|---|
| Agent orchestration | LangGraph | Graph model fits the retrieve → grade → rewrite/retry → synthesize loop with explicit conditional edges and a retry cap; built-in checkpointing gives run persistence/resumability for free. | The loop structure changes fundamentally (e.g. becomes a true multi-agent/parallel workflow) beyond what a single StateGraph expresses well. |
| Caching | Redis | Sub-millisecond key-value cache with TTL support, well-suited to hashing (query, prompt) → (result); already the standard choice for this pattern. | Cache working set or throughput outgrows a single Redis instance's practical capacity (would move to Redis Cluster, not a different technology). |
| ORM | Prisma Client Python | Typed schema-first models shared conceptually with a Next.js frontend's Prisma familiarity; migrations are declarative and reviewable. | Prisma Client Python's feature/stability gap with the JS client becomes a blocker for a needed Postgres feature. |
| Vector store | **Undecided** — in-memory, pgvector, and Qdrant are all behind the `memory/base.py` interface; no backend is committed for v1. | Long-term memory volume in v1 (a customer's own past runs) is small and doesn't yet justify a dedicated vector database; pgvector reuses the existing Postgres instance if/when needed. | Corpus exceeds roughly 500k chunks, or filtering/hybrid-search needs outgrow what pgvector handles well — at that point, commit to pgvector (moderate scale, stays in Postgres) or Qdrant (larger scale or advanced filtering). |
| Web search tool | **OpenAI `web_search` (Responses API)** — `tools/web_search_openai.py`, the sole/permanent implementation. | Tavily's marketing/dashboard site (tavily.com, api.tavily.com root) was unreliably reachable from this network during Feature 2 setup, blocking sign-up; OpenAI's built-in web_search tool works through the `OPENAI_API_KEY` already funded for the LLM calls, so no second provider/key was needed to unblock the feature. Real measured cost: **≈$0.0855 for 8 calls** in a live test run (2 eval queries + 1 manual retry-loop check); ongoing rate is **$10.00/1,000 calls + search-content tokens billed at standard model rates** (gpt-4o-mini: $0.15/1M input, $0.60/1M output) — notably pricier per call than Tavily's ~$0.008/basic-search credit (or free under 1,000 credits/month). Response shape also differs materially from a typical raw-result search API: OpenAI returns a synthesized answer with citation annotations, not independent raw search results — see `tools/web_search_openai.py`'s module docstring for how that's adapted to the `{title, url, content}` shape the Grader node expects. | OpenAI web_search's per-call cost (~$10/1,000 calls + tokens) or its synthesized-excerpt response shape becomes a real problem. Tavily (previously evaluated, then fully removed — `tools/web_search.py` and `TAVILY_API_KEY` no longer exist in this codebase) or another raw-result search API would need to be re-evaluated and re-implemented from scratch behind the `Tool` interface (`tools/base.py`), not swapped back in. |

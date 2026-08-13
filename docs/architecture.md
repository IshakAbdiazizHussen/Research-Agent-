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
| LangGraph checkpoint storage location | Dedicated Postgres schema `langgraph_checkpoints` (same database, separate namespace from `public`), set via connection `search_path` in `agent/checkpointer.py`. | LangGraph's official `AsyncPostgresSaver` names its own table `checkpoints` — the exact name our `Checkpoint` Prisma model maps to (`@@map("checkpoints")`) in `public`. Its first `setup()` run hit a real `psycopg.errors.UndefinedColumn: column "thread_id" does not exist`, because it found our existing, differently-shaped table (camelCase `threadId`, our columns) and tried to migrate it instead of creating its own. Scoping its tables to their own schema fixed this without touching `public.checkpoints` or `schema.prisma`. | The custom `Checkpoint` Prisma model (unused since this decision) is ever revisited/removed, or LangGraph's saver adds native table-prefix/schema configuration that makes the manual `search_path` workaround unnecessary. |
| Background run execution | Detached `asyncio.create_task` (`api/routes/research.py`), not FastAPI's `BackgroundTasks`. | `POST /research` must return immediately while `GET /research/{id}/stream` — a separate, later request — observes progress; `BackgroundTasks` ties a task to the request/response cycle it was created in, which is the wrong lifecycle here. Progress is read back via polling `Message` rows in Postgres rather than in-memory task state, which also happens to stay correct under horizontal scaling (multiple uvicorn workers/processes, where a request could land on a different worker than the one running the task) — worth noting explicitly since that scenario was not tested directly (single dev instance only). | Running multiple worker processes/instances in production is actually adopted — confirm the polling-based design holds up under real concurrent load, and that orphaned-run resume (`resume_orphaned_runs()`, per-instance at startup) doesn't double-resume the same run if two instances start close together. |
| Orphaned run resumption guards | Staleness threshold (1hr, based on last Message activity) and max resume attempts (3, tracked via Message rows with `stepType="resume_attempt"`) before abandoning a run as `"failed"` — no schema changes, both checks reuse existing Message/ResearchRun structures. | `resume_orphaned_runs()` (Feature 4) had no age or attempt limit, discovered to be silently re-attempting a genuinely stuck run on every pytest session via the app lifespan, firing real live OpenAI calls each time with no visibility. Also fixed root cause of a related issue found during investigation: `test_research_api.py` wasn't cleaning up its own ResearchRun/Message/User rows, causing dev-database pollution (12 leftover runs, 19 stray users found and removed). | If legitimate runs ever need to resume after being stale for longer than 1hr (e.g. very long-running research), the threshold may need to become configurable rather than a fixed constant. |
| SSE frame parsing (frontend) | `fetch()`-based manual SSE parsing instead of native `EventSource`; normalizes `\r\n` to `\n` before frame-splitting. | `EventSource` cannot send custom headers, required for the stream endpoint's `X-Dev-User-Email` auth. A real bug was found and fixed during manual QA: the backend sends `\r\n\r\n` frame delimiters, but the initial parser searched for `\n\n` only, silently discarding the entire stream with the UI stuck on "Working..." forever. Confirmed via instrumented before/after traces against a dedicated logged backend instance. | N/A — this is a correctness fix, not a deferred decision. |
| Next.js version / npm audit vulnerabilities | Stayed on Next 15; 3 high-severity transitive vulnerabilities (postcss, sharp, via Next.js itself) left unresolved. | Fixable only via a breaking Next 15→16 major upgrade; current app is dev-only/local with no untrusted CSS or image input, so risk doesn't apply yet. | Before any production deployment, or before accepting untrusted user-uploaded images/content. |
| Database name | `research_agent_dev` (kept as-is, not renamed to `"Research Agent"`). | Attempted renaming to `"Research Agent"` (space + capitals) for cosmetic reasons; Prisma Client Python's connection engine percent-encodes the database name from `DATABASE_URL` but never decodes it back before using it as the literal Postgres identifier, causing `P1003: database does not exist` regardless of encoding approach (`%20`, raw space, `+` all tested and failed identically). Confirmed no newer Prisma release resolves this (0.15.0 is latest). Reverted cleanly, no lasting changes. | A different Postgres connection layer is adopted, or a future Prisma Client Python release is confirmed to fix this decoding behavior. |
| Web search tool | **OpenAI `web_search` (Responses API)** — `tools/web_search_openai.py`, the sole/permanent implementation. | Tavily's marketing/dashboard site (tavily.com, api.tavily.com root) was unreliably reachable from this network during Feature 2 setup, blocking sign-up; OpenAI's built-in web_search tool works through the `OPENAI_API_KEY` already funded for the LLM calls, so no second provider/key was needed to unblock the feature. Real measured cost: **≈$0.0855 for 8 calls** in a live test run (2 eval queries + 1 manual retry-loop check); ongoing rate is **$10.00/1,000 calls + search-content tokens billed at standard model rates** (gpt-4o-mini: $0.15/1M input, $0.60/1M output) — notably pricier per call than Tavily's ~$0.008/basic-search credit (or free under 1,000 credits/month). Response shape also differs materially from a typical raw-result search API: OpenAI returns a synthesized answer with citation annotations, not independent raw search results — see `tools/web_search_openai.py`'s module docstring for how that's adapted to the `{title, url, content}` shape the Grader node expects. **Final note, accepted as a known trade-off, not a bug:** OpenAI's `web_search` occasionally answers broad conceptual queries (e.g. "How AI Agents work?", "How saas systems work?") from its own knowledge without invoking/citing search at all, regardless of retries — confirmed via direct raw API inspection (zero `annotations`, no `web_search_call` item in the response). In that case the graph correctly hits its retry cap and returns an honest "no sources available" answer rather than fabricating one — this is the system behaving as designed under a real tool limitation, not a grader or retrieval bug (traced and ruled out: the grader was never even invoked with any documents to reject). A Brave Search API fallback and a full switch back to Tavily as primary were both considered and explicitly declined — see Revisit when. | OpenAI web_search's per-call cost (~$10/1,000 calls + tokens) or its synthesized-excerpt response shape becomes a real problem, **or** Tavily becomes reliably reachable again, **or** a different search provider is adopted for other reasons. Tavily (`tools/web_search.py`, `TAVILY_API_KEY`) was fully removed from this codebase (not left dormant) and remains unreachable due to a persistent CloudFront block on its marketing/auth site, confirmed across multiple separate sessions — re-adopting it would mean re-implementing it from scratch behind the `Tool` interface (`tools/base.py`), not swapping a registration back. A Brave Search API fallback (single last-resort call after retry-loop exhaustion) was scoped in detail but not built — declined in favor of accepting the "no sources" outcome as honest and correct, not worth a second provider dependency + cost for. |

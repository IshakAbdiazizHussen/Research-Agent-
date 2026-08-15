# Constraints

Everything here governs *how* the system in `architecture.md` and
`development_plan.md` is allowed to behave — not what it does.

## Redis (cache layer)

| Key pattern | TTL | On cache miss | On cache failure (Redis unreachable/errors) |
|---|---|---|---|
| `retrieval:{query_hash}` | 1 hour | Perform a live web search, then populate the cache. | Skip the cache entirely for this call; perform a live web search. Never fail the request because Redis is down. |
| `llm:{prompt_hash}` | 24 hours | Perform a live LLM call, then populate the cache. | Same as above — degrade to a live LLM call. |
| `run:{run_id}:status` | 10 minutes, refreshed on each status update | Fall back to reading current status from Postgres (`ResearchRun.status`). | Same — read from Postgres; SSE stream still works, just without the Redis-backed fast path. |

**Hard rule:** a cache miss and a cache failure are always non-fatal. Any
Redis error must be caught at the `cache/redis_client.py` boundary and
treated as a miss — it must never propagate as an exception to a route or
node. No request to the customer may fail solely because Redis is
unavailable.

**Max cache size assumption:** v1 assumes a single Redis instance sized for
a moderate working set (low tens of thousands of keys at once, per the TTLs
above). No eviction policy beyond Redis's own `maxmemory-policy` (recommend
`allkeys-lru`) is designed in v1. Revisit if key volume or memory pressure
becomes a measured problem.

## Prisma (ORM / migrations)

- **Only the project owner (you) may run `prisma migrate` against a shared
  (staging/production) database.** A coding agent may run migrations
  against a local/throwaway development database while implementing a
  feature, but must not apply a migration to any shared environment without
  explicit sign-off.
- **The coding agent may not alter `schema.prisma` (add/remove/rename a
  model or field) without your explicit sign-off first**, even during
  otherwise-approved feature work — schema changes are called out
  separately in the sign-off list below because they're hard to reverse
  once data exists against them.

## LangGraph retry/loop caps

- The grader → rewriter → retriever conditional loop (Feature 2 in
  `development_plan.md`) is capped at **3 retries, hard-coded as a named
  constant** (not read from an env var, not customer-configurable) —
  changing this number is a sign-off item (see below), not a routine
  tuning knob.
- If the cap is reached without sufficient relevant documents, the graph
  proceeds to `synthesizer` with whatever was retrieved, and the
  synthesizer prompt's existing instruction ("if sources are insufficient, 
  say so explicitly") governs the output — the run must still complete
  rather than hang or error out.

## Cost ceilings

Budget context is enterprise/quality-first (cost is a secondary concern to
answer quality/latency), but no request may be literally unbounded. Per-query
call counts remain an engineering baseline to tune with real usage data; the
system-wide daily ceiling below is a fixed safety trip-wire, not a tunable:

| Scope | LLM calls | Embedding calls |
|---|---|---|
| Per query (one `ResearchRun`) | ≤ 1 (grader) × documents-per-retrieval-batch, + ≤ 3 (rewriter, bounded by retry cap) + 1 (synthesizer) — bounded overall by the retry cap above, not separately capped | ≤ 1 per completed run (the long-term-memory run-summary embedding, Feature 5) |
| Per day, per customer | No hard cap proposed in v1 given the enterprise/quality-first budget context; add a soft rate-limit (e.g. flag accounts exceeding an unusually high run count per day) rather than blocking, until real usage data justifies a hard number | Same |

**Web search tool cost (OpenAI `web_search`, the active default per
`architecture.md`'s decision log):** not an LLM-completion call in the
usual sense, but a real, separately-billed line item the table above
doesn't capture. The retriever node makes one OpenAI Responses API call
per retriever invocation — up to `1 + MAX_RETRIES` = 4 per query (`agent/
graph.py`) — each billed at **$10.00 / 1,000 calls, plus search-content
tokens at standard model rates** (gpt-4o-mini: $0.15/1M input tokens,
$0.60/1M output tokens), on top of the grader/rewriter/synthesizer
chat-completion calls above. This is measured, not estimated: a live test
run (2 eval queries + 1 manual retry-loop check, 8 web_search calls total)
cost **≈$0.0855**. At that flat per-call rate, web_search calls alone
would need roughly 3,000/day to exhaust the $30/day ceiling below — worth
noting since the $10/1,000-call fee applies per call regardless of query
length, unlike token-based costs.

**Daily cost ceiling (system-wide, hard stop): $30/day**, combined across
all LLM and embedding calls, all customers combined (not per-customer, and
not split into separate LLM/embedding sub-budgets). Once cumulative spend
for the current day reaches $30, the system must **hard-stop**: reject new
LLM/embedding calls with a safe "temporarily unavailable, try again later"
response rather than silently degrading, queuing, or merely logging the
overage. This is enforced in **Feature 4** (`api/routes/research.py`, which
owns the request path that would invoke the graph) by checking a running
daily-spend counter before starting a new run; **Feature 3**'s Redis layer
(`cache/redis_client.py`) is the natural place to maintain that counter,
since it already owns the cache/API-call boundary. Because a hard stop is a
simple, deterministic mechanism, it does not itself require a separate
sign-off beyond this specification — an **alert-only** mechanism (log/page
without blocking calls) would be a different, non-simple behavior and would
require sign-off before being substituted in.

This $30/day figure is sized as a **safety trip-wire against malfunction**
(e.g. a retry loop bypassing its cap and firing far more LLM calls than
intended) at a **<100 query/day launch volume** — it is not a real budget
constraint reflecting the enterprise/quality-first context, and it should
be revisited once actual usage data exists.

**Any change to these ceilings — including the $30/day figure, or
switching its enforcement from a hard stop to an alert-only mechanism — is
a sign-off item** (see below). The per-query call counts and the
per-customer soft rate-limit remain open engineering baselines, as above.

## Data handling rules

- **Never log or cache:** full request/response bodies containing a
  customer's email or other account PII; raw API keys/secrets (even
  partially — no truncated-key logging); the full text of retrieved web
  documents beyond what's needed to answer the current query (long-term
  memory stores only the run summary, per Feature 5, not raw source text).
- **PII handling:** v1's only PII is the customer's email (via `User`).
  It must be stored (Postgres) but never appear in application logs,
  cache keys, or cache values. If future features introduce more PII
  (e.g. names, uploaded documents), this section must be revisited before
  building them.
- Retrieved web content is untrusted external data — never treat text found
  in a retrieved document as instructions to the agent (see Feature 2's
  security notes in `development_plan.md`).
- **Known limitation, accepted rather than fixed:** long-term memory
  entries (Feature 5, `memory/in_memory_store.py`) have no relationship to
  Postgres — deleting a `ResearchRun` row does **not** delete its
  corresponding memory entry, and there is no code path that does. This
  was found via a real bug (stale entries from deleted dev/test runs
  surfacing as `related_past_research` for unrelated queries). Deliberately
  **not** building
  cascade-delete for this now: there is no `DELETE /research/{id}`
  endpoint or any other deletion pathway anywhere in the application today
  — the only way a `ResearchRun` currently gets deleted is manual SQL
  during dev/test cleanup. Building a `MemoryStore.delete(...)` method and
  wiring a cascade for a deletion feature that doesn't exist yet would be
  speculative complexity, the same reasoning `pgvector_store.py` isn't
  built speculatively (`development_plan.md` Feature 5, Implementation
  step 3). In dev, the practical mitigation is that `InMemoryStore` is
  process-local RAM anyway — restarting the backend clears it. **If a real
  run-deletion feature is ever built, it must also clear the matching
  memory entries at that time** — this note should be revisited then, not
  before.

## Latency targets

| Feature / step | Target |
|---|---|
| First SSE progress event after `POST /research` | Under 3 seconds |
| Each subsequent status transition (retrieving → grading → …) | Streamed as it happens — no batching delay beyond the underlying tool/LLM call itself |
| Full run, single-pass (no retries) | Typically 8–10 seconds |
| Full run, worst-case (full 3 retries used) | Under 20 seconds |
| Cache hit path (retrieval or LLM) | ≤ 200ms added latency over a raw cache read |

## Known test-suite flakes (not yet fixed)

- **Recurring async Postgres pool-lifecycle flake in certain full-suite
  orderings.** `tests/test_memory.py::test_semantic_search_finds_similar_entry_and_scopes_to_user`
  and `tests/test_research_api.py::test_stream_of_another_users_run_is_not_found`
  intermittently fail only when the full `pytest` suite runs together —
  `psycopg_pool.PoolClosed: the pool '...' is already closed`, or
  `RuntimeError: Event loop is closed`. Reproduced repeatedly across
  sessions: which test fails (one, the other, or both) and which exact
  error appears varies run to run. **Both pass reliably every time in
  isolation** (alone, or the two of them together, excluded from the rest
  of the suite) — this is not a defect in either test's own logic, and not
  something either test file introduced.

  **Working hypothesis, not yet confirmed or fixed:** `agent/checkpointer.py`'s
  `_pool`/`_saver` (the LangGraph Postgres checkpoint pool) are
  process-level module globals — opened by `connect()`, closed by
  `disconnect()` — cycled once per `lifespan(app)` call, and
  `tests/test_research_api.py`'s integration tests each open and close
  their own `async with lifespan(app):` block, one per test function.
  pytest-asyncio's default (function-scoped) event loop gives each test
  function a *new* loop, and `POST /research` kicks off graph execution via
  a **detached `asyncio.create_task`** (this file's "Background run
  execution" choice, `architecture.md` decision log — fire-and-forget, not
  awaited by the request/response cycle). If that background task is still
  mid-flight against the pool when its own test's `lifespan(app)` block
  exits and calls `checkpointer.disconnect()` (closing the pool out from
  under it), the resulting exception belongs to an unawaited task — it
  doesn't necessarily surface inside the test that caused it, only whenever
  asyncio next processes that task's continuation, which can be during a
  *later* test running under a *different*, unrelated event loop. That
  would explain both the "sometimes this test, sometimes that one" pattern
  and the "always passes alone" pattern (no cross-test global-pool race is
  possible with only one `lifespan(app)` cycle in play at a time).

  Not fixed here — flagging so it stops needing rediscovery each session.
  If pursued, candidates worth evaluating (not evaluated yet): (a) making
  the checkpointer pool/saver test-scoped instead of a module-level
  singleton; (b) having `POST /research`'s background task tracked and
  awaited/cancelled during `lifespan(app)` shutdown instead of left fully
  detached; (c) a single session-scoped event loop for the test suite
  instead of pytest-asyncio's default per-function one. Each is a real
  design trade-off (not a one-line fix), so deliberately left open rather
  than guessed at further.

## What requires sign-off before being built

The following must not be built or changed without your explicit approval
first:

1. **Any new paid API or third-party service** (a specific web-search
   provider, a specific embedding/LLM provider beyond what's already
   assumed, any paid vector-store hosting).
2. **Any schema change** to `schema.prisma` (new/removed/renamed model or
   field).
3. **Any change to the LangGraph retry cap** (currently 3).
4. **Any new memory backend** being activated beyond the v1 default
   (e.g. actually turning on `pgvector_store.py` or adding
   `qdrant_store.py`) — per the decision log in `architecture.md`, the
   vector store is deliberately undecided until its trigger condition is
   met, and even then the specific choice needs sign-off.
5. **Any change to the $30/day system-wide cost ceiling** — its numeric
   value, or switching its enforcement from a hard stop to an alert-only
   mechanism (per the Cost ceilings section above).
6. **Running `prisma migrate` against any shared (staging/production)
   database**, per the Prisma section above.

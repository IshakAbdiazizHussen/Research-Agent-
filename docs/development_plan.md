# Development Plan

Features are derived from the problem breakdown in `project_definition.md`
and ordered by dependency — each feature builds on artifacts the previous
ones created.

## Quality Assurance template

Every feature's **Quality Assurance** section must include explicit
lint/build/test commands appropriate to what that feature touches, not
just a "tests pass" statement:

- **Backend/Python features:** `ruff check .` (lint), `mypy .` if
  type-checking is in use, and `pytest` (tests) — all run from `backend/`,
  all must pass with zero errors before the feature is considered done.
  (`mypy` is not currently configured/in use in this codebase — no
  `mypy.ini`, not enforced anywhere — so it's omitted from features below
  until/unless that changes; the template line stays conditional for when
  it does.)
- **Frontend/Next.js features (starting Feature 6):** `npm run lint`,
  `npm run build`, and `npm run test` if a test runner is configured — all
  run from `frontend/`, all must pass before the feature is considered
  done.
- **Don't cross the streams:** a backend-only feature's QA section does not
  need the `npm` commands, and a frontend-only feature's QA section does
  not need `ruff`/`mypy`/`pytest`. Only include commands relevant to what
  that specific feature actually touches.

---

## Feature 1: User Identity & Data Foundation

**Read four docs before you did the update or moving to next feature.**

### Spec
Establishes the durable data layer everything else writes to: the `User`,
`ResearchRun`, `Message`, and `Checkpoint` Prisma models, a Postgres
connection, and minimal user identity so a run can be attributed to a
customer. Inputs: none (foundational). Outputs: a working Prisma
client/session, migrated schema, and a way to resolve "current user" for a
request. Fits Step 4 of the problem breakdown (the target user is an
identified external customer, not anonymous) and is a prerequisite for
Step 3's persistence requirement.

### Prompts
None — this feature is infrastructure only, no LLM calls.

### Security
Must not log raw email addresses or any user PII to application logs (hash
or omit in log lines). No authentication *method* is specified yet by the
user of this plan (e.g. which auth provider) — treat wiring a specific auth
provider as requiring sign-off per `constraints.md` before building it;
until then, a minimal stand-in (e.g. a signed session/user-id header) is
acceptable for local development only, clearly marked as non-production.

### Guidelines
All schema lives in `backend/app/db/prisma/schema.prisma` — no ad hoc SQL
migrations outside Prisma. Field names and enums must match
`architecture.md`'s Prisma model definitions exactly (`status` enum values,
`sources` as json, etc.). Nothing here should hardcode a database URL or
credentials — they come from `core/config.py` reading environment variables.

### Implementation
1. Write `backend/app/db/prisma/schema.prisma` with `User`, `ResearchRun`,
   `Message`, `Checkpoint` models as specified in `architecture.md`.
2. Run initial `prisma migrate` (per the sign-off policy in
   `constraints.md`) against a local/dev Postgres instance.
3. Implement `backend/app/db/prisma_client.py` — a single shared Prisma
   Client Python instance with connect/disconnect lifecycle hooks for
   FastAPI startup/shutdown.
4. Implement `backend/app/core/config.py` (env-driven settings: database
   URL, Redis URL, etc.) and `backend/app/core/logging.py` (structured
   logging setup that never logs full user PII).
5. Add a minimal current-user resolution mechanism (dev-only stand-in,
   documented as such) used by later routes.

### Quality Assurance
- Backend feature — from `backend/`, run `ruff check .` and `pytest`; both
  must pass with zero errors (`mypy` omitted — not configured/in use in
  this codebase; no `npm` commands — this feature touches no frontend
  code).
- Migration applies cleanly to a fresh database.
- A `User` and a `ResearchRun` row can be created and read back via the
  Prisma client in a standalone script/test.
- Manually confirm no PII appears in log output at any log level.
- Done when: schema is migrated, `prisma_client.py` is importable and
  connects/disconnects cleanly in a FastAPI lifespan test, and a smoke
  test creates+reads one row of each model.

---

## Feature 2: Core Research Agent Graph

**Read four docs before you did the update or moving to next feature.**

### Spec
The heart of the system: a LangGraph `StateGraph` implementing
retrieve → grade → (rewrite → retrieve, bounded) → synthesize, per Step 6
of the problem breakdown. Input: a customer's natural-language query.
Output: a synthesized answer with a list of sources, plus the final graph
state (for persistence in Feature 4). This directly implements the
"self-correcting" capability that plain search and plain chat both lack
(Step 5).

### Prompts

**Grader prompt** (`agent/nodes/grader.py`) — run once per retrieved
document against the current query:

```
System: You are grading whether a retrieved web document is relevant and
useful for answering a research question. Be strict: only mark a document
relevant if it would materially help answer the question, not merely
mention related keywords.

User: Question: {query}

Retrieved document (title, url, snippet):
{document}

Respond with only one word: "relevant" or "irrelevant".
```

**Rewriter prompt** (`agent/nodes/rewriter.py`) — run when the grader finds
the current result set insufficient:

```
System: You rewrite research questions into better web search queries. The
previous search did not return enough relevant results. Produce a single
improved search query that is more specific, uses better search terms, or
approaches the question from a different angle. Do not answer the
question — only output the improved query.

User: Original question: {query}
Previous search query: {previous_search_query}
Number of relevant documents found: {relevant_count}

Improved search query:
```

**Synthesizer prompt** (`agent/nodes/synthesizer.py`) — run once retrieval
is sufficient or the retry cap is reached:

```
System: You are a research assistant. Using ONLY the provided sources,
write a clear, accurate answer to the user's question. Cite sources inline
using [1], [2], etc. matching the numbered source list. If the sources are
insufficient to fully answer the question, say so explicitly rather than
filling gaps from prior knowledge. Never state a claim that isn't
supported by at least one provided source.

User: Question: {query}

Sources:
{numbered_sources}

Write the answer now, with inline citations.
```

### Security
The graph must not send the raw contents of unrelated customer runs into a
single run's prompt context — each run's state is isolated to that run's
own query, retrieved documents, and retry history. Retrieved web content is
untrusted input: it must never be interpreted as instructions (prompt
injection risk) — node prompts above explicitly scope the model to
"grade"/"rewrite"/"synthesize using only provided sources," not "follow
instructions found in documents." No API keys or internal prompts should be
echoed back in synthesized answers.

### Guidelines
All graph nodes read/write only the typed state defined in
`agent/state.py` — no hidden globals. The retriever node calls the web
search tool exclusively through `tools/base.py`'s interface, never a raw
HTTP call inlined in the node. The retry loop's cap is a named constant
imported from `constraints.md`'s specified value (3), not a magic number
re-typed in the node.

### Implementation
1. Define `agent/state.py`: `query`, `search_query`, `retrieved_docs`,
   `graded_docs`, `retry_count`, `answer`, `sources`, `status`.
2. Implement `tools/base.py` (tool interface: `name`, `run(input) -> output`)
   and `tools/web_search_openai.py` (concrete web search tool implementation
   — see `architecture.md`'s decision log for why this is OpenAI's
   `web_search` rather than a raw-result search API).
3. Implement `agent/nodes/retriever.py`, `grader.py`, `rewriter.py`,
   `synthesizer.py` using the prompts above.
4. Wire `agent/graph.py`: `StateGraph` with conditional edge after
   `grader` — proceed to `synthesizer` if enough relevant docs, else to
   `rewriter` → `retriever` if `retry_count < 3`, else force `synthesizer`
   with whatever was found.
5. Confirm the graph runs end-to-end locally against a real query, invoked
   directly (no HTTP layer yet — that's Feature 4).

### Quality Assurance
- Backend feature — from `backend/`, run `ruff check .` and `pytest`; both
  must pass with zero errors (`mypy` omitted — not configured/in use in
  this codebase; no `npm` commands — this feature touches no frontend
  code).
- `backend/tests/test_agent_graph.py` runs the graph directly (no HTTP)
  against a handful of hand-picked queries and asserts: an answer is
  produced, sources are non-empty, and `retry_count` never exceeds 3.
- Manually run one query with deliberately poor initial phrasing and
  confirm the rewrite loop triggers and improves results.
- Done when: the graph produces a cited answer for a representative sample
  of eval-set questions (see Feature 7) without manual intervention, and
  never loops past the retry cap.

---

## Feature 3: Retrieval & LLM Result Caching

**Read four docs before you did the update or moving to next feature.**

### Spec
Wraps the web search tool and the LLM calls inside the graph nodes with a
Redis-backed cache, per Step 5 of the problem breakdown (avoid redundant
cost/latency on repeated or overlapping queries). Input: the same
tool/LLM calls Feature 2 already makes. Output: identical results, served
from cache when available, with graceful fallback to a live call on any
cache miss or cache failure.

### Prompts
None new — this feature does not introduce or modify any LLM prompt, only
wraps existing calls.

### Security
Cached values must not include any customer-identifying data beyond what's
strictly needed to key the cache (query/prompt hash, not raw user id in the
value). Cache failures must never be surfaced to the customer as an error —
they degrade to a live call (see `constraints.md`).

### Guidelines
No node or tool touches the Redis client directly — everything goes through
`cache/redis_client.py`'s `get_cached`/`set_cached` interface, matching the
architecture's stated boundary. TTLs are the named constants from
`architecture.md`'s Redis table, not re-typed per call site.

### Implementation
1. Implement `cache/redis_client.py`: connection setup plus
   `get_cached(key)` / `set_cached(key, value, ttl)`, with try/except around
   all Redis operations that falls back to "miss" behavior on any error.
2. Add a `retrieval:{query_hash}` cache check/set around the web search
   tool call in `tools/web_search_openai.py`.
3. Add an `llm:{prompt_hash}` cache check/set around each LLM call in
   `grader.py`, `rewriter.py`, `synthesizer.py`.
4. Confirm cache hits skip the live call entirely and cache misses/failures
   fall through to a live call transparently.

### Quality Assurance
- Backend feature — from `backend/`, run `ruff check .` and `pytest`; both
  must pass with zero errors (`mypy` omitted — not configured/in use in
  this codebase; no `npm` commands — this feature touches no frontend
  code).
- Unit test: same query run twice in immediate succession results in only
  one live web-search call (second is a cache hit).
- Unit test: simulated Redis connection failure still returns a correct
  result (degrades to live call, no exception propagates to the caller).
- Manually verify cache key format matches `architecture.md` exactly.
- Done when: repeated identical queries measurably skip live calls, and a
  forced Redis outage does not break a run.

---

## Feature 4: Research Run API & Streaming Progress

**Read four docs before you did the update or moving to next feature.**

### Spec
Exposes the graph (Feature 2) over HTTP with streaming progress, and
persists each run using the models from Feature 1 — this is what makes
research runs visible and revisitable (Step 3). Input: `POST /research`
with `{query}`; output: a `ResearchRun` id, then `GET
/research/{id}/stream` emits SSE events for each status transition
(`retrieving`, `grading`, `rewriting`, `synthesizing`, `completed`,
`failed`) ending with the final answer and sources.

### Prompts
None new — this feature invokes the graph from Feature 2 without adding
prompts of its own.

### Security
`GET /research/{id}/stream` and any run-read endpoint must verify the
requesting user owns the run (`ResearchRun.userId` matches the current
user) before streaming or returning data — one customer must never be able
to read another customer's run by guessing/enumerating ids. Internal error
details (stack traces, raw exception text) must never be forwarded into an
SSE event visible to the customer; log them server-side instead.

### Guidelines
The route layer (`api/routes/research.py`) only orchestrates: it calls into
`agent/graph.py` and the Prisma client, and must not contain business logic
that belongs in a node or tool. LangGraph's checkpointer must be configured
against the `Checkpoint` Prisma model / Postgres, not left as the default
in-memory checkpointer, so runs survive a process restart.

### Implementation
1. Configure a Postgres-backed LangGraph checkpointer keyed by
   `thread_id = ResearchRun.id`, persisting to the `Checkpoint` model.
2. Implement `POST /research`: create a `ResearchRun` row (`status =
   pending`), kick off graph execution asynchronously, return the run id.
3. Implement `GET /research/{id}/stream`: subscribe to graph execution
   progress (LangGraph streaming API) and emit one SSE event per node
   transition, updating `ResearchRun.status` in Postgres at each step.
4. On completion, write `answer`, `sources`, `status = completed`,
   `completedAt` to the `ResearchRun` row; on failure, `status = failed`
   with a safe (non-internal) error message.
5. Add ownership checks (`userId` match) to both endpoints.

### Quality Assurance
- Backend feature — from `backend/`, run `ruff check .` and `pytest`; both
  must pass with zero errors (`mypy` omitted — not configured/in use in
  this codebase; no `npm` commands — this feature touches no frontend
  code).
- Integration test: `POST /research` followed by consuming
  `GET /research/{id}/stream` yields status events in the expected order
  and ends with a completed answer.
- Integration test: requesting another user's run id returns a
  not-found/forbidden response, not the data.
- Manually kill and restart the backend mid-run and confirm the checkpoint
  allows the run to resume or at least fail cleanly rather than corrupt
  state.
- Done when: a full run is streamable end-to-end over HTTP and persisted
  correctly, matching the schema in `architecture.md`.

---

## Feature 5: Long-Term Memory & Past Run Retrieval

**Read four docs before you did the update or moving to next feature.**

### Spec
Lets a customer's completed runs inform future ones and be searched later,
per Step 4 (repeat customers, no memory today). Input: a completed
`ResearchRun`. Output: a stored memory entry (behind the swappable
`memory/base.py` interface) and a `search()` capability the graph or API
can use to surface a customer's related past research.

### Prompts

**Run-summary prompt** (`memory/base.py` caller, e.g. invoked after
`synthesizer`) — used to produce a compact text to embed and store:

```
System: Summarize the following research question and answer in 2-3
sentences, suitable for later semantic search. Preserve the key entities
and conclusion; omit filler.

User: Question: {query}
Answer: {answer}

Summary:
```

### Security
Long-term memory entries are scoped per `userId` — `search()` must never
return another customer's stored memories. No raw source document content
is stored in long-term memory, only the run-level summary and metadata, to
limit what's retained about external (potentially licensed/paywalled) web
content.

### Guidelines
All memory access goes through `memory/base.py`'s `store()`/`search()`
interface — nodes, routes, and tests interact with that interface only,
never with `in_memory_store.py` or `pgvector_store.py` directly, so the
backend stays swappable per the decision log in `architecture.md`. Do not
hardcode a specific vector store choice anywhere outside the concrete
store implementation files themselves.

### Implementation
1. Define `memory/base.py`: `store(user_id, text, metadata) -> None` and
   `search(user_id, query, top_k) -> list[MemoryResult]`.
2. Implement `memory/in_memory_store.py` as the default v1 backend (no new
   infrastructure required) implementing that interface.
3. Implement `memory/pgvector_store.py` only when/if the trigger condition
   in `architecture.md`'s decision log is met — not built speculatively in
   this pass.
4. After a run completes (Feature 4's completion step), generate the
   run-summary above, embed it, and call `store()`.
5. Optionally surface `search()` results ("related past research") in the
   API response when a new run starts.

### Quality Assurance
- Backend feature — from `backend/`, run `ruff check .` and `pytest`; both
  must pass with zero errors (`mypy` omitted — not configured/in use in
  this codebase; no `npm` commands — this feature touches no frontend
  code).
- Unit test: storing then searching returns the stored entry for a
  semantically similar query, and never returns another user's entry.
- Unit test: swapping the configured backend from in-memory to a stub
  alternate implementation requires no changes outside `memory/base.py`'s
  callers' configuration.
- Done when: a completed run is retrievable via semantic search scoped to
  its owning customer.

---

## Feature 6: Frontend Research UI

**Read four docs before you did the update or moving to next feature.**

### Spec
The customer-facing surface: submit a query, watch streamed progress, and
read the final cited answer — directly addressing Step 3's "no visibility
into progress" and Step 5's "no sourced, readable answer" failures. Input:
customer interaction (typing a query, submitting). Output: rendered
progress states and final answer with clickable sources, matching the
backend's response/event schema.

### Prompts
None — frontend only, no LLM calls originate here.

### Security
`lib/api.ts` must never embed or expose backend secrets/API keys in
client-side code (Next.js `NEXT_PUBLIC_*` vars only for genuinely public
values). The SSE client must handle a stream ending in a `failed` status by
showing a safe, generic error — never rendering raw backend error text that
could leak internal details.

### Guidelines
`types/research.ts` must mirror the backend's Pydantic/SSE event schema
exactly (kept in sync manually until/unless a shared-schema generation step
is added — not assumed here). All backend calls go through
`lib/api.ts`/`lib/sse.ts`, never inline `fetch`/`EventSource` calls inside
components.

### Implementation
1. Implement `types/research.ts` matching `ResearchRun` fields and SSE
   event shapes from Feature 4.
2. Implement `lib/api.ts` (`POST /research` wrapper) and `lib/sse.ts`
   (`EventSource` wrapper with reconnect/close handling).
3. Implement `components/chat/QueryInput.tsx`,
   `components/chat/StreamingStatus.tsx` (renders retrieving/grading/etc.),
   `components/chat/MessageList.tsx` (renders final answer + numbered
   sources).
4. Wire `app/page.tsx` and `app/layout.tsx` to compose the above into a
   working research flow.

### Quality Assurance
- Frontend feature — from `frontend/`, run `npm run lint`, `npm run build`,
  and `npm run test` if a test runner is configured; all must pass (no
  `ruff`/`mypy`/`pytest` — this feature touches no backend code).
- Manual test: submit a query, observe each streaming status render in
  order, see a final answer with clickable numbered sources.
- Manual test: kill the backend mid-stream and confirm the UI shows a
  graceful error, not a crash.
- Done when: a customer can complete a full research query end-to-end
  through the UI with no direct API/CLI interaction required.

---

## Feature 7: Evaluation & Quality Harness

**Read four docs before you did the update or moving to next feature.**

### Spec
Operationalizes the success criteria from `project_definition.md` into a
repeatable check. Input: `backend/tests/eval/eval_set.json`
(question/expected-answer pairs). Output: a pass/fail or scored report
against the groundedness, answer-quality, and loop-convergence criteria.

### Prompts

**LLM-judge prompt** (used by the eval harness, not the production graph):

```
System: You are grading a research assistant's answer against a reference
answer. Score "correct" only if the answer's key claims match the
reference answer's key claims and are supported by cited sources. Score
"incorrect" otherwise, including partially right-but-misleading answers.

User: Question: {query}
Reference answer: {expected_answer}
Assistant's answer (with sources): {actual_answer}

Respond with only one word: "correct" or "incorrect".
```

### Security
Eval runs must use non-production credentials/quota where possible and
must not write eval traffic into the same long-term memory store real
customers search against (keep eval user ids clearly namespaced/excluded).

### Guidelines
Eval questions and expected answers live only in
`backend/tests/eval/eval_set.json` — no hardcoded eval questions scattered
in test files. `test_agent_graph.py` calls the graph directly (per
`architecture.md`), not through the HTTP layer, to keep the eval fast and
isolated from API/auth concerns.

### Implementation
1. Populate `backend/tests/eval/eval_set.json` with an initial set of
   research questions and reference answers (starting size to be agreed
   before implementation — not invented here).
2. Implement an eval runner that executes the graph for each question and
   applies the LLM-judge prompt above.
3. Compute and report the three eval-facing metrics from
   `project_definition.md`: groundedness rate, judged-correct rate, and
   retry-cap-exhaustion rate.
4. Wire the eval runner into CI (or a documented manual command) so it can
   be re-run after any node/prompt change.

### Quality Assurance
- Backend feature — from `backend/`, run `ruff check .` and `pytest`; both
  must pass with zero errors (`mypy` omitted — not configured/in use in
  this codebase; no `npm` commands — this feature touches no frontend
  code).
- The eval runner itself is tested against a tiny fixed fixture (2-3
  questions with known expected outcomes) to confirm scoring logic is
  correct before trusting it on the full eval set.
- Done when: running the eval harness produces the three metrics defined
  in `project_definition.md`'s success criteria against the current graph.

---

## Feature 8: Landing Page & Theme System

**Read four docs before you did the update or moving to next feature.**

### Spec
**Unlike Features 1-7, this does not trace to a step in `project_definition.md`'s
Section 1 problem breakdown** — that breakdown scopes the research-agent
capability itself (retrieval, grading, synthesis, persistence), and has no
analog for a marketing/landing surface or a light/dark theme system. This
is user-commissioned product-surface work layered on top of the completed
v1 capability (a growth/first-impression surface, and a visual preference
users of any web app reasonably expect), not a fix for one of the
original failure modes. Flagged explicitly rather than forcing a fake
"traces to Step X" justification the way Features 1-7 legitimately can.
It's captured as a Feature (not just an `architecture.md` decision log
row, the pattern used for smaller implementation-level changes throughout
Features 6/7's follow-up work) because of its actual size: a new route, a
new page, and an app-wide theming architecture change touching every
existing CSS rule, not a tweak to one already-shipped piece.

Two parts. **Part 1 — Landing page:** the chat interface moves from `/`
to `/app`; `/` becomes a new marketing landing page (hero + "How it
works" + "Key capabilities" + repeated CTA) linking into `/app`. **Part
2 — Theme system:** a light/dark toggle, reachable from both the landing
page and the chat interface, applying to the entire app (not just the
new landing page) — including bubbles, the streaming-status indicator,
error states, and the related-past-research card that were built
dark-only through Feature 6/7's follow-up work.

### Prompts
None — frontend only, no LLM calls originate here.

### Security
No new attack surface: the theme choice and chat history (already
covered by Feature 6's follow-up work) are the only things in
`localStorage`, both non-sensitive, both client-side/this-browser-only by
design — no new data leaves the browser, no new backend endpoint. The
theme-init script (`app/layout.tsx`) reads/writes only its own
namespaced `localStorage` key, wrapped in try/catch so a broken/
unavailable storage can't block the page from rendering.

### Guidelines
Every color in `app/globals.css` must resolve through a themed CSS
custom property (`--color-*`, `--hero-gradient`, `--toggle-bg`) — no
hardcoded hex/rgb color introduced outside the three theme-definition
blocks at the top of the file (bare `:root`, the
`prefers-color-scheme: dark` media query, and `:root[data-theme="dark"]`).
The dark palette in the latter two blocks must stay pixel-identical to
each other and to the app's original (pre-Feature-8) dark-only values —
this is a re-homing of already-shipped, already-verified colors into
theme-scoped selectors, not a redesign of dark mode. `lib/theme.ts` is
the single source of truth for the storage key and light/dark precedence
logic for anything running *after* hydration; the inline script in
`app/layout.tsx` necessarily duplicates that logic in dependency-free
JS (it must run before any bundled module, including `lib/theme.ts`, is
parsed) — if the precedence rule ever changes, both places need updating,
by construction, not an oversight to avoid.

### Implementation
1. Move the existing chat interface from `app/page.tsx` to
   `app/app/page.tsx` (the `/app` route) unchanged apart from adding the
   theme toggle to its header.
2. Restructure `app/globals.css`'s token definitions into the three-layer
   theme pattern (bare `:root` = light/default, `@media
   (prefers-color-scheme: dark)` guarded with `:root:not([data-theme="light"])`,
   and `:root[data-theme="dark"]`) — audit and convert every other
   hardcoded color in the file into one of these tokens.
3. `lib/theme.ts`: `getStoredTheme()` / `setStoredTheme()` /
   `getSystemTheme()` / `getActiveTheme()` / `applyTheme()` — same
   never-throws, `typeof window === "undefined"`-guarded contract as
   `lib/historyStorage.ts`.
4. `components/theme/ThemeToggle.tsx`: a small client component reused
   in both the landing hero and the chat header; label names the theme
   clicking it switches *to*.
5. `app/layout.tsx`: a synchronous (non-async, non-deferred) inline
   `<script>` in `<head>`, setting `[data-theme]` on `<html>` before
   first paint, plus `suppressHydrationWarning` on that same element
   (required, not optional — the script's pre-hydration attribute write
   is a genuine, expected difference from the server-rendered HTML that
   React would otherwise warn about on every load).
6. New `app/page.tsx`: the landing page. Rebuilt once against an exact
   reference image partway through this feature (not just the earlier
   from-description pass) — one continuous `--hero-gradient` spans the
   hero *and* "How it works" *and* "Key capabilities" (`.landing-page`),
   not a hero-only gradient handing off to a flat `--color-bg` section;
   both sections' cards are translucent/frosted (`--card-glass-bg`/
   `-border`, `backdrop-filter: blur()`) so the gradient shows through,
   with light-circle/dark-text step-number badges (`--badge-bg`); a
   `--landing-footer-bg` flat color (the gradient's own deepest tone)
   for the closing CTA/footer below the fold, which the reference didn't
   show. Repeated CTA links to `/app` via `next/link`.

### Quality Assurance
- Frontend feature — from `frontend/`, run `npm run lint` and
  `npm run build`; both must pass (no `ruff`/`mypy`/`pytest` — this
  feature touches no backend code).
- Manual/Playwright test: screenshot the landing page and the chat
  interface (with a real exchange) in both themes — bubbles, citations,
  and the streaming-status indicator (checkmark/active-dot rows) must all
  stay legible and correctly styled in both.
- Manual/Playwright test: toggle the theme, reload, confirm it persisted
  (`localStorage` + the re-rendered `[data-theme]` attribute).
- No hydration-mismatch console errors on load, in either theme (a real
  one was found and fixed during this feature's own QA — see
  `suppressHydrationWarning` above — not assumed clean).
- No excess dead space between the hero and "How it works": a real bug
  (`.landing-hero`'s `min-height: 100vh`/`100dvh`, later removed — it
  forced the hero to always fill the full viewport regardless of its own
  much shorter content, leaving ~275px of dead centered whitespace)
  confirmed by measuring computed height/gap via Playwright before
  changing anything — `heroActualHeight` was byte-equal to
  `window.innerHeight` at two different viewport heights, proving the
  min-height was binding, not assumed from a screenshot. Fixed by
  removing it (height now comes from content + padding alone); re-
  measured gap between the CTA and "How it works" dropped from
  274px/278px (desktop/mobile) to 64px/64px. **Follow-up:** 64px then
  read as too tight against the CTA button — raised `.landing-hero`'s
  bottom padding from `4rem` to `8rem` (the entire gap is that one
  padding value, `.landing-sections` has no top padding of its own),
  re-measured at 128px/128px. Still a single, deliberate, proportionate
  padding value — not a reintroduction of the removed min-height bug's
  viewport-chasing behavior.
- No flash-of-wrong-theme: verified by pre-seeding `localStorage` with a
  non-default theme choice, then inspecting `[data-theme]` and the
  computed body background at `domcontentloaded` (the earliest practical
  inspection point) — both already correct that early, identical again
  after full page settle — plus confirming the init script tag itself is
  non-async/non-deferred/non-module, which is *why* a flash is
  structurally not possible, not just an empirical one-run observation.
- Done when: both routes render correctly in both themes, the toggle is
  reachable and persists from both pages, and none of Feature 6/7's
  already-verified chat behavior (bubble alignment, streaming-status
  collapse-on-completion, chat history persistence, CORS) regressed.

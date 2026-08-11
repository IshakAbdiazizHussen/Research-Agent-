# Project Definition

## 1. Step-by-step problem breakdown

**Step 1 — The situation today.** A customer using our product has an open-ended
question they want a reliable, well-sourced answer to (e.g. "what are the
current best practices for X," "compare A and B," "summarize the latest
developments in Y"). Today they have two realistic options: open a search
engine and manually work through several results, or open a plain LLM chat
and ask it directly. Neither is part of a coherent, product-native workflow —
each is a manual detour the customer takes outside our product.

**Step 2 — What's missing.** Neither of those options combines *live,
multi-source retrieval* with *LLM synthesis* in a way that self-corrects. A
search engine gives links, not an answer. A plain LLM chat gives an answer,
but with no live web access (so it may be stale), no citations (so it can't
be checked), and no mechanism to notice "these results are weak, let me
rephrase and search again" — it just answers once, confidently, from
whatever it already knows.

**Step 3 — What specifically fails without this system.** Without a system
that retrieves, grades what it finds, retries when retrieval is weak, and
only then synthesizes, the customer is stuck doing the cross-checking work
themselves (slow, manual, easy to miss sources) or trusting an ungrounded
answer (fast, but unverifiable and sometimes wrong). There is also no
persisted record of the research: no way to see what was searched, what
sources were used, or to revisit a past answer — every research session
starts from zero.

**Step 4 — Who experiences that failure.** This is the product's external
customers — people using the product to get research done as part of their
own work, not internal staff. They are not necessarily technical; they want
an answer with visible sourcing, not a transcript of an agent's internal
reasoning, and they want to come back later and find what they researched
before.

**Step 5 — Why simpler solutions don't solve it.** Plain search returns raw
links and leaves synthesis and cross-checking to the customer — it doesn't
scale to "give me an answer," only to "give me places to look." Plain LLM
chat synthesizes fluently but has no live retrieval, no citations, and no
self-correction loop, so it can be confidently wrong and there is no way for
the customer to verify it without doing the research themselves anyway. A
spreadsheet has no automation, no live web access, and no natural-language
interface — it's a place to record research someone already did, not a way
to do it.

**Step 6 — The shape of what's actually needed.** Given the above, the
system needs to be a stateful, multi-step agent: retrieve from the live web,
grade the relevance/quality of what came back, rewrite the query and retry
(bounded, not infinite) when results are weak, and only synthesize a cited
answer once retrieval is good enough. The run needs to be persisted (so
progress can stream to the customer and be revisited later), and repeat
customers benefit from the system remembering their own past research.

## 2. Classification

| Axis | Classification |
|---|---|
| Problem type | Retrieval-augmented generation with a corrective/self-reflective loop (retrieve → grade → rewrite/retry → synthesize) — a multi-step agentic task, not single-shot RAG and not plain chat. |
| Domain | Open/public-domain web research — general-purpose, not a fixed vertical (no legal/medical/financial specialization assumed for v1). |
| Complexity class | Multi-step research with a bounded retry loop and persisted run state. Not a single-turn lookup (there's a grade/retry loop); not a continuous stateful agent (each run has a defined start and end, not an open-ended ongoing session). |
| Data characteristics | Unstructured (web pages/search snippets), effectively unbounded volume (the open web via a search API), high update frequency (live, no static corpus to pre-index). Long-term memory data (the customer's own past runs) is small-volume and structured/semi-structured by contrast. |

## 3. Target user and current workaround

**Target user:** external customers of the product — people who use the
product's research capability as part of their own work. Not internal staff,
not developers of the product itself.

**Current workaround:** they manually run searches across several browser
tabs, skim and cross-check sources themselves, and either take their own
notes or paste snippets into a general-purpose LLM chat tool and hope it
doesn't hallucinate. There is no sourced, persisted, revisitable record of
that work — it lives in browser history and scattered notes, if anywhere.

## 4. In scope / out of scope for v1

Every line traces back to a numbered step in Section 1.

### In scope (v1)

| Scope item | Traces to |
|---|---|
| Single research query → multi-step agentic run: retrieve → grade → rewrite/retry (bounded) → synthesize | Step 6 |
| Web search as the retrieval tool (via a `Tool` interface, provider swappable) | Step 6 (live web needed, not a static corpus) |
| Cited sources attached to the synthesized answer | Step 5 (fixes the "unverifiable" failure of plain chat) |
| Streaming progress (SSE) so the customer sees retrieving/grading/synthesizing status as it happens | Step 3 (visibility into an otherwise opaque multi-step process) |
| Persisted research runs (Postgres via Prisma) so a run and its answer can be revisited later | Step 3 (no persisted record today) |
| Caching of retrieval and LLM results (Redis) to cut duplicate cost/latency on repeated or overlapping queries | Step 5 (manual cross-checking is slow; repeated LLM/search calls are wasteful) |
| Long-term memory of a customer's own past queries/answers (vector store, swappable backend) so repeat use benefits from prior research | Step 4 (repeat customers, no memory today) |
| Basic user identity so runs are attributed to the correct customer | Step 4 (target user is an external, identified customer, not anonymous) |

### Out of scope (v1)

| Scope item | Rationale (traces to Section 1) |
|---|---|
| Private/internal document corpora (customer-uploaded files, enterprise KB ingestion) | Step 6/Step 2 established the v1 need as *live web* retrieval; no private data source was specified as part of the problem. Revisit if customers need to research over their own documents. |
| Multi-turn conversational follow-up within a single run (v1 = one query → one run; a follow-up is a new run) | Not required by any step in the breakdown; the failure described in Step 3 is about single-question research being unsourced/unpersisted, not about conversational continuity. |
| Multi-user collaboration/sharing of a research run | Step 4 defines the user as an individual customer; sharing wasn't identified as part of the failure being solved. |
| Non-web tools (code execution, database querying, proprietary/internal APIs) | Step 6 only motivates a web-search tool; other tools have no grounding in the breakdown yet. |
| Fine-grained roles/permissions beyond "this run belongs to this customer" | Step 4 only requires attribution, not a permissions model. |

## 5. Success criteria

A v1 build is considered working when, measured against a maintained
eval set (`backend/tests/eval/eval_set.json`) of research questions:

1. **Groundedness:** ≥ 80% of eval answers include at least one valid,
   relevant cited source per key claim (no unsourced factual claims in the
   synthesized answer).
2. **Answer quality:** ≥ 80% of eval answers are rated correct/relevant by
   an LLM-judge or human reviewer against the expected-answer reference.
3. **Loop convergence:** ≥ 95% of eval queries reach synthesis without
   exhausting the retry cap (grader → rewriter → retriever loop, capped at 3
   retries per `constraints.md`) — i.e. the self-correction loop usually
   resolves rather than always maxing out.
4. **Visible progress:** the customer receives the first SSE progress event
   within the latency target defined in `constraints.md` (not silence until
   the final answer).
5. **Persistence:** every completed run is retrievable afterward via its run
   ID with its original query, sources, and answer intact.
6. **Caching effectiveness:** repeated/overlapping queries within a cache
   TTL window measurably hit the Redis cache (tracked via cache hit rate)
   rather than re-issuing identical search/LLM calls.

These thresholds (80%, 95%) are proposed starting targets, not
externally mandated numbers — revisit them once real eval data exists.

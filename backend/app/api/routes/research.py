"""Research run API (Feature 4: Research Run API & Streaming Progress).

POST /research creates a ResearchRun and kicks off graph execution as a
detached asyncio task (not a FastAPI BackgroundTask — that ties a task to
the request/response cycle, which is wrong here since a *later*, separate
request is what observes it). GET /research/{id}/stream polls the run's
Message rows (an append-only, strictly-ordered event log — sequence never
skips, so no transition is lost regardless of poll timing) and streams new
ones as SSE until the run reaches a terminal status.

This route layer only orchestrates (docs/development_plan.md Guidelines):
it calls into agent/graph.py and the Prisma client, no business logic here.
"""

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from prisma import Json
from prisma.models import User
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.agent.checkpointer import get_checkpointer
from app.agent.graph import build_graph, initial_state
from app.agent.llm_client import complete
from app.core.deps import get_current_user
from app.db.prisma_client import prisma
from app.memory.base import MemoryResult, get_memory_store

logger = logging.getLogger(__name__)

router = APIRouter()

_TERMINAL_STATUSES = {"completed", "failed"}
_STREAM_POLL_SECONDS = 0.3
_STREAM_MAX_WAIT_SECONDS = 120

# Guards for resume_orphaned_runs() (Feature 4 bug fix — see docs/
# architecture.md decision log): a non-terminal run with no recent activity
# is almost certainly abandoned, not legitimately paused, and re-attempting
# it forever (e.g. once per pytest session, each firing real API calls) is
# a real cost leak, not a resumability feature. No schema change was made
# to track this — "recent activity" reuses Message.createdAt (already
# exists), and "attempt count" is tracked as ordinary Message rows
# (stepType="resume_attempt") rather than a new ResearchRun column, per
# docs/constraints.md's sign-off requirement for schema changes.
_RESUME_STALENESS_THRESHOLD = timedelta(hours=1)
_MAX_RESUME_ATTEMPTS = 3

# Feature 5 memory-store step: a real production failure traced to this
# (see docs/architecture.md decision log) reproduced as a clean success
# when retried directly with identical input — evidence of a transient
# failure (rate limit / network blip), not a deterministic bug. This step
# had zero retry resilience, so a single transient hiccup permanently lost
# that memory entry. One retry closes that gap without turning a
# best-effort step into something that can block/fail the run.
_MEMORY_STORE_MAX_ATTEMPTS = 2
_MEMORY_STORE_RETRY_DELAY_SECONDS = 2.0

# Minimum cosine-similarity score for a memory-search result to be worth
# surfacing as "related past research" at all. Without this, search()
# unconditionally returns its top-K regardless of how weak the match is —
# observed in practice returning ~5-41% matches (structurally-similar-but-
# unrelated short questions, e.g. two different "capital of X" queries) as
# if they were meaningfully related. 0.3 is a starting default (not
# calibrated against real eval data yet, same spirit as this project's
# other starting thresholds, e.g. agent/graph.py's MIN_RELEVANT_DOCS) —
# tune once real usage data exists. Applied here, at the caller, not inside
# MemoryStore.search() — "what's worth showing a user" is this route's
# call, not a storage-backend concern every backend would have to
# reimplement identically.
_MIN_RELATED_RESEARCH_SCORE = 0.3

# Strong references to in-flight background runs — asyncio does not
# guarantee an unreferenced Task won't be garbage-collected mid-run.
_background_tasks: set[asyncio.Task] = set()

# Feature 5 (Long-Term Memory) run-summary prompt — verbatim from
# docs/development_plan.md; do not edit here without updating that doc.
_SUMMARY_SYSTEM_PROMPT = """Summarize the following research question and answer in 2-3
sentences, suitable for later semantic search. Preserve the key entities
and conclusion; omit filler."""

_SUMMARY_USER_PROMPT_TEMPLATE = """Question: {query}
Answer: {answer}

Summary:"""


class ResearchRequest(BaseModel):
    query: str


class ResearchRunCreated(BaseModel):
    id: str
    # Feature 5, optional per docs/development_plan.md ("Optionally surface
    # search() results"). Empty for a customer's first-ever run.
    related_past_research: list[MemoryResult] = []


def _describe_step(node_name: str, update: dict[str, Any]) -> str:
    if node_name == "retriever":
        return f"Retrieving sources for: {update.get('search_query', '')}"
    if node_name == "grader":
        graded = update.get("graded_docs") or []
        relevant = sum(1 for d in graded if d.get("relevant"))
        return f"Graded {len(graded)} retrieved document(s), {relevant} relevant."
    if node_name == "rewriter":
        return f"Insufficient results — rewriting search query to: {update.get('search_query', '')}"
    return f"{node_name} step completed."


async def _next_sequence(run_id: str) -> int:
    latest = await prisma.message.find_first(
        where={"runId": run_id}, order={"sequence": "desc"}
    )
    return (latest.sequence + 1) if latest else 0


async def _store_run_memory(*, user_id: str, run_id: str, query: str, answer: str) -> None:
    """Generate the run-summary and store it in long-term memory. Best-
    effort with one retry (see _MEMORY_STORE_MAX_ATTEMPTS above) — a
    failure here must never fail the run itself, whose actual answer
    already succeeded, so the final failure is logged, never re-raised."""
    summary_prompt = _SUMMARY_USER_PROMPT_TEMPLATE.format(query=query, answer=answer)

    for attempt in range(1, _MEMORY_STORE_MAX_ATTEMPTS + 1):
        try:
            summary = await complete(_SUMMARY_SYSTEM_PROMPT, summary_prompt)
            await get_memory_store().store(user_id, summary, {"run_id": run_id, "query": query})
            return
        except Exception as exc:
            if attempt < _MEMORY_STORE_MAX_ATTEMPTS:
                logger.warning(
                    "long-term memory store attempt %s/%s failed for run_id=%s: "
                    "%s: %s — retrying in %.0fs",
                    attempt,
                    _MEMORY_STORE_MAX_ATTEMPTS,
                    run_id,
                    type(exc).__name__,
                    exc,
                    _MEMORY_STORE_RETRY_DELAY_SECONDS,
                )
                await asyncio.sleep(_MEMORY_STORE_RETRY_DELAY_SECONDS)
            else:
                logger.exception(
                    "failed to store long-term memory for run_id=%s after %s attempt(s): %s: %s",
                    run_id,
                    _MEMORY_STORE_MAX_ATTEMPTS,
                    type(exc).__name__,
                    exc,
                )


async def _run_graph_and_persist(run_id: str, query: str, *, resume: bool = False) -> None:
    """The background worker. Never lets an exception escape uncaught — a
    failure here must land the run in `status=failed` with a safe message,
    not crash silently or leave the row stuck (docs/development_plan.md
    Security: internal error details never reach the customer)."""
    seq = await _next_sequence(run_id)

    async def record(role: str, content: str, step_type: str | None) -> None:
        nonlocal seq
        await prisma.message.create(
            data={
                "runId": run_id,
                "role": role,
                "content": content,
                "stepType": step_type,
                "sequence": seq,
            }
        )
        seq += 1

    # Seed from whatever's already persisted (0 for a fresh run; the last
    # value written before a crash for a resumed one) — this is a summary
    # field kept in sync with the graph's real retry_count, not a separate
    # source of truth (that's still the Message transcript / checkpoint).
    run_row = await prisma.researchrun.find_unique(where={"id": run_id})
    retry_count = run_row.retryCount if run_row else 0

    try:
        checkpointer = get_checkpointer()
        graph = build_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": run_id}}
        graph_input = None if resume else initial_state(query)

        async for event in graph.astream(graph_input, config=config, stream_mode="updates"):
            for node_name, update in event.items():
                if "retry_count" in update:
                    retry_count = update["retry_count"]

                status = update.get("status")
                if status:
                    await prisma.researchrun.update(
                        where={"id": run_id},
                        data={"status": status, "retryCount": retry_count},
                    )
                    await record("tool", _describe_step(node_name, update), status)

                if node_name == "synthesizer":
                    answer = update.get("answer") or ""
                    sources = update.get("sources") or []
                    await prisma.researchrun.update(
                        where={"id": run_id},
                        data={
                            "status": "completed",
                            "answer": answer,
                            "sources": Json(sources),
                            "completedAt": datetime.now(UTC),
                        },
                    )
                    await record("assistant", answer, "completed")

                    if run_row is not None:
                        await _store_run_memory(
                            user_id=run_row.userId, run_id=run_id, query=query, answer=answer
                        )
    except Exception:
        logger.exception("research run failed: run_id=%s", run_id)
        try:
            await prisma.researchrun.update(
                where={"id": run_id},
                data={"status": "failed", "completedAt": datetime.now(UTC)},
            )
            await record(
                "assistant",
                "This research run could not be completed. Please try again.",
                "failed",
            )
        except Exception:
            logger.exception("failed to persist failure state for run_id=%s", run_id)


def _spawn_run(run_id: str, query: str, *, resume: bool = False) -> None:
    task = asyncio.create_task(_run_graph_and_persist(run_id, query, resume=resume))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def _abandon_run(run_id: str, reason: str) -> None:
    """Mark a run terminal without attempting to resume it. Uses the
    existing `failed` status rather than a new "abandoned" enum value —
    adding one would be a schema.prisma change requiring sign-off per
    docs/constraints.md, which this fix intentionally avoids."""
    logger.warning("abandoning orphaned run, not resuming: run_id=%s reason=%s", run_id, reason)
    await prisma.researchrun.update(
        where={"id": run_id},
        data={"status": "failed", "completedAt": datetime.now(UTC)},
    )
    seq = await _next_sequence(run_id)
    await prisma.message.create(
        data={
            "runId": run_id,
            "role": "assistant",
            "content": "This research run was abandoned (stuck too long or too many failed "
            "resume attempts) and could not be completed. Please try again.",
            "stepType": "failed",
            "sequence": seq,
        }
    )


async def resume_orphaned_runs() -> None:
    """Called once at app startup (after the checkpointer connects) — any
    run left in a non-terminal status from before a restart/crash has no
    background task tracking it anymore. Resume it from its last checkpoint
    (docs/development_plan.md QA: "confirm the checkpoint allows the run to
    resume") — but only if it looks legitimately interrupted, not abandoned:

    - Stale: its most recent Message is older than
      _RESUME_STALENESS_THRESHOLD (default 1h). A run that's had zero
      progress in that long was not "just restarted", it's dead.
    - Attempted too many times already: _MAX_RESUME_ATTEMPTS
      resume_attempt markers already exist for it. Without this, a run
      that reliably fails to resume gets retried once per app/test startup
      forever — a real, silent, recurring cost leak (this is exactly what
      happened before this fix: a stuck run from Feature 4 testing was
      re-attempted, and a real API call fired, on every subsequent pytest
      run for hours).

    Either condition lands the run on status=failed via _abandon_run()
    instead of spawning a resume task."""
    orphaned = await prisma.researchrun.find_many(
        where={"status": {"in": ["pending", "retrieving", "grading", "rewriting", "synthesizing"]}}
    )
    now = datetime.now(UTC)

    for run in orphaned:
        latest_message = await prisma.message.find_first(
            where={"runId": run.id}, order={"sequence": "desc"}
        )
        raw_last_activity = latest_message.createdAt if latest_message else run.createdAt
        last_activity = _as_utc(raw_last_activity)
        age = now - last_activity

        attempt_count = await prisma.message.count(
            where={"runId": run.id, "stepType": "resume_attempt"}
        )

        if age > _RESUME_STALENESS_THRESHOLD:
            await _abandon_run(run.id, f"stale, last activity {age} ago")
            continue
        if attempt_count >= _MAX_RESUME_ATTEMPTS:
            await _abandon_run(run.id, f"exceeded max resume attempts ({attempt_count})")
            continue

        logger.warning(
            "resuming orphaned research run after restart: run_id=%s (attempt %s/%s)",
            run.id,
            attempt_count + 1,
            _MAX_RESUME_ATTEMPTS,
        )
        seq = await _next_sequence(run.id)
        await prisma.message.create(
            data={
                "runId": run.id,
                "role": "system",
                "content": f"Resume attempt {attempt_count + 1}/{_MAX_RESUME_ATTEMPTS}.",
                "stepType": "resume_attempt",
                "sequence": seq,
            }
        )
        _spawn_run(run.id, run.query, resume=True)


@router.post("/research", response_model=ResearchRunCreated, status_code=201)
async def create_research_run(
    payload: ResearchRequest, current_user: User = Depends(get_current_user)
) -> ResearchRunCreated:
    run = await prisma.researchrun.create(
        data={"userId": current_user.id, "query": payload.query}
    )
    await prisma.message.create(
        data={
            "runId": run.id,
            "role": "user",
            "content": payload.query,
            "sequence": 0,
        }
    )

    _spawn_run(run.id, payload.query)

    # Feature 5, optional and best-effort: surfacing related past research
    # must never block/fail run creation if memory search errors.
    related: list[MemoryResult] = []
    try:
        candidates = await get_memory_store().search(current_user.id, payload.query, top_k=3)
        related = [r for r in candidates if r["score"] >= _MIN_RELATED_RESEARCH_SCORE]
    except Exception:
        logger.exception("failed to search long-term memory for user_id=%s", current_user.id)

    return ResearchRunCreated(id=run.id, related_past_research=related)


@router.get("/research/{run_id}/stream")
async def stream_research(run_id: str, current_user: User = Depends(get_current_user)):
    run = await prisma.researchrun.find_unique(where={"id": run_id})
    # 404 for both "doesn't exist" and "exists but isn't yours" — a 403
    # would confirm the id exists to someone enumerating ids, which is
    # exactly what we must not do (docs/development_plan.md Security).
    if run is None or run.userId != current_user.id:
        raise HTTPException(status_code=404, detail="Research run not found.")

    async def event_generator():
        cursor = -1
        elapsed = 0.0

        while True:
            messages = await prisma.message.find_many(
                where={"runId": run_id, "sequence": {"gt": cursor}},
                order={"sequence": "asc"},
            )
            for message in messages:
                cursor = message.sequence
                yield {
                    "event": "progress",
                    "data": json.dumps(
                        {
                            "sequence": message.sequence,
                            "role": message.role,
                            "status": message.stepType,
                            "content": message.content,
                        }
                    ),
                }

            current = await prisma.researchrun.find_unique(where={"id": run_id})
            if current is not None and current.status in _TERMINAL_STATUSES:
                yield {
                    "event": "done",
                    "data": json.dumps(
                        {
                            "status": current.status,
                            "answer": current.answer,
                            "sources": current.sources,
                        }
                    ),
                }
                return

            await asyncio.sleep(_STREAM_POLL_SECONDS)
            elapsed += _STREAM_POLL_SECONDS
            if elapsed >= _STREAM_MAX_WAIT_SECONDS:
                yield {
                    "event": "done",
                    "data": json.dumps(
                        {
                            "status": "failed",
                            "answer": None,
                            "sources": [],
                            "note": "stream timed out waiting for the run to finish",
                        }
                    ),
                }
                return

    return EventSourceResponse(event_generator())

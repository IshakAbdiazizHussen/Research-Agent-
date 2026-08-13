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
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from prisma import Json
from prisma.models import User
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.agent.checkpointer import get_checkpointer
from app.agent.graph import build_graph, initial_state
from app.core.deps import get_current_user
from app.db.prisma_client import prisma

logger = logging.getLogger(__name__)

router = APIRouter()

_TERMINAL_STATUSES = {"completed", "failed"}
_STREAM_POLL_SECONDS = 0.3
_STREAM_MAX_WAIT_SECONDS = 120

# Strong references to in-flight background runs — asyncio does not
# guarantee an unreferenced Task won't be garbage-collected mid-run.
_background_tasks: set[asyncio.Task] = set()


class ResearchRequest(BaseModel):
    query: str


class ResearchRunCreated(BaseModel):
    id: str


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


async def resume_orphaned_runs() -> None:
    """Called once at app startup (after the checkpointer connects) — any
    run left in a non-terminal status from before a restart/crash has no
    background task tracking it anymore. Resume it from its last checkpoint
    (docs/development_plan.md QA: "confirm the checkpoint allows the run to
    resume"); if resuming itself fails, _run_graph_and_persist's own
    try/except still lands it on status=failed rather than stuck forever."""
    orphaned = await prisma.researchrun.find_many(
        where={"status": {"in": ["pending", "retrieving", "grading", "rewriting", "synthesizing"]}}
    )
    for run in orphaned:
        logger.warning("resuming orphaned research run after restart: run_id=%s", run.id)
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

    return ResearchRunCreated(id=run.id)


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

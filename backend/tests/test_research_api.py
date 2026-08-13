"""Feature 4 (Research Run API & Streaming Progress) integration tests.

Runs against the real app (real lifespan, real Postgres, real checkpointer,
real Redis) via httpx against the ASGI app directly — but the OpenAI SDK
calls are mocked (same approach as test_cache.py) so these tests exercise
the real API/DB/SSE/checkpointer plumbing without live network cost or
non-determinism. Feature 2's own live tests already prove the graph itself
works against the real OpenAI API; these tests are about the route layer.

Each test cleans up the ResearchRun/Message/User rows it creates in a
finally block (same convention as tests/test_data_foundation.py) — these
tests previously left rows behind on every run, which is exactly the test
noise that made a real orphaned-run bug (see docs/architecture.md decision
log, resume_orphaned_runs) harder to spot in the dev database.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from openai.resources.chat.completions.completions import AsyncCompletions
from openai.resources.responses.responses import AsyncResponses

from app.api.routes import research as research_module
from app.db.prisma_client import prisma
from app.main import app, lifespan


def _fake_responses_create(*args, **kwargs):
    text = "Berlin is the capital of Germany, per source one and source two."
    citation_a = SimpleNamespace(
        type="url_citation", url="https://example.com/a", title="Source A",
        start_index=0, end_index=30,
    )
    citation_b = SimpleNamespace(
        type="url_citation", url="https://example.com/b", title="Source B",
        start_index=31, end_index=65,
    )
    content_part = SimpleNamespace(text=text, annotations=[citation_a, citation_b])
    message_item = SimpleNamespace(type="message", content=[content_part])
    return SimpleNamespace(output=[message_item])


def _fake_chat_completions_create(*args, **kwargs):
    messages = kwargs.get("messages", [])
    system_content = messages[0]["content"] if messages else ""
    if "grading whether a retrieved web document" in system_content:
        content = "relevant"
    else:
        content = "Berlin is the capital of Germany [1][2]."
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


async def _consume_sse(response: httpx.Response) -> list[dict]:
    events: list[dict] = []
    event_type = None
    async for line in response.aiter_lines():
        if line.startswith("event:"):
            event_type = line.removeprefix("event:").strip()
        elif line.startswith("data:"):
            data = json.loads(line.removeprefix("data:").strip())
            events.append({"event": event_type, "data": data})
    return events


async def _cleanup(*, run_ids: list[str], user_emails: list[str]) -> None:
    for run_id in run_ids:
        await prisma.message.delete_many(where={"runId": run_id})
        await prisma.researchrun.delete_many(where={"id": run_id})
    for email in user_emails:
        await prisma.user.delete_many(where={"email": email})


@pytest.fixture
def mocked_openai():
    responses_patch = patch.object(
        AsyncResponses, "create", AsyncMock(side_effect=_fake_responses_create)
    )
    completions_patch = patch.object(
        AsyncCompletions, "create", AsyncMock(side_effect=_fake_chat_completions_create)
    )
    with responses_patch, completions_patch:
        yield


async def test_post_then_stream_yields_ordered_progress_and_completes(mocked_openai):
    query = f"integration test query {uuid.uuid4()}"
    email = f"user-a-{uuid.uuid4()}@test.local"
    headers = {"X-Dev-User-Email": email}
    run_id = None

    async with lifespan(app):
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                create_resp = await client.post(
                    "/research", json={"query": query}, headers=headers
                )
                assert create_resp.status_code == 201
                run_id = create_resp.json()["id"]

                async with client.stream(
                    "GET", f"/research/{run_id}/stream", headers=headers, timeout=30.0
                ) as stream_resp:
                    assert stream_resp.status_code == 200
                    events = await _consume_sse(stream_resp)

            assert events, "expected at least one SSE event"
            progress_events = [e for e in events if e["event"] == "progress"]
            done_events = [e for e in events if e["event"] == "done"]

            assert len(done_events) == 1
            assert done_events[0]["data"]["status"] == "completed"
            assert done_events[0]["data"]["answer"]
            assert done_events[0]["data"]["sources"]

            # Strictly increasing sequence — no transition lost or duplicated.
            sequences = [e["data"]["sequence"] for e in progress_events]
            assert sequences == sorted(sequences)
            assert sequences == list(range(len(sequences)))

            # First progress event is always the original user query (sequence 0).
            assert progress_events[0]["data"]["role"] == "user"
            assert progress_events[0]["data"]["content"] == query
        finally:
            await _cleanup(run_ids=[run_id] if run_id else [], user_emails=[email])


async def test_stream_of_another_users_run_is_not_found(mocked_openai):
    query = f"integration test query {uuid.uuid4()}"
    owner_email = f"owner-{uuid.uuid4()}@test.local"
    other_email = f"other-{uuid.uuid4()}@test.local"
    owner_headers = {"X-Dev-User-Email": owner_email}
    other_headers = {"X-Dev-User-Email": other_email}
    run_id = None

    async with lifespan(app):
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                create_resp = await client.post(
                    "/research", json={"query": query}, headers=owner_headers
                )
                assert create_resp.status_code == 201
                run_id = create_resp.json()["id"]

                forbidden_resp = await client.get(
                    f"/research/{run_id}/stream", headers=other_headers
                )
                assert forbidden_resp.status_code == 404

                nonexistent_resp = await client.get(
                    "/research/does-not-exist/stream", headers=owner_headers
                )
                assert nonexistent_resp.status_code == 404
        finally:
            await _cleanup(
                run_ids=[run_id] if run_id else [],
                user_emails=[owner_email, other_email],
            )


# --- resume_orphaned_runs() guard tests -------------------------------
#
# These build the "orphaned run" state directly in the database (never via
# POST /research) and call resume_orphaned_runs() as a plain function —
# no live graph execution, no real timing race, no server restart. That's
# deliberate: manual timing-based testing of this (kill a real process
# mid-flight, hope the backdate lands before it completes) proved flaky —
# "stuff"'s retry behavior is non-deterministic, so the run kept completing
# before the kill/backdate could take effect. Testing the guard's logic
# directly against controlled database state removes that race entirely.
#
# _spawn_run is patched rather than asserting on the OpenAI mocks: even a
# guard that incorrectly decided to resume only *schedules* a background
# task via asyncio.create_task — it wouldn't necessarily have made its live
# call yet by the time we check, since that task hasn't been given a chance
# to run. Whether _spawn_run itself was invoked for this run_id is the
# actual decision the guard makes, and checking it is instant and exact.


async def test_resume_orphaned_runs_abandons_stale_run():
    email = f"staleness-test-{uuid.uuid4()}@test.local"
    run_id = None

    async with lifespan(app):
        try:
            user = await prisma.user.create(data={"email": email})
            run = await prisma.researchrun.create(
                data={"userId": user.id, "query": "stuff", "status": "retrieving"}
            )
            run_id = run.id

            backdated = datetime.now(UTC) - timedelta(hours=2)
            await prisma.message.create(
                data={
                    "runId": run_id,
                    "role": "user",
                    "content": "stuff",
                    "sequence": 0,
                    "createdAt": backdated,
                }
            )

            with patch.object(research_module, "_spawn_run") as spawn_mock:
                await research_module.resume_orphaned_runs()

            spawned_run_ids = [call.args[0] for call in spawn_mock.call_args_list]
            assert run_id not in spawned_run_ids, "a stale run must not be resumed"

            updated = await prisma.researchrun.find_unique(where={"id": run_id})
            assert updated.status == "failed"

            resume_markers = await prisma.message.find_many(
                where={"runId": run_id, "stepType": "resume_attempt"}
            )
            assert resume_markers == [], "abandoning must not itself log a resume attempt"
        finally:
            await _cleanup(run_ids=[run_id] if run_id else [], user_emails=[email])


async def test_resume_orphaned_runs_abandons_after_max_attempts():
    email = f"max-attempts-test-{uuid.uuid4()}@test.local"
    run_id = None

    async with lifespan(app):
        try:
            user = await prisma.user.create(data={"email": email})
            run = await prisma.researchrun.create(
                data={"userId": user.id, "query": "stuff", "status": "grading"}
            )
            run_id = run.id

            # Recent activity (not stale) — isolates the attempt-count path
            # from the staleness path tested above.
            recent = datetime.now(UTC) - timedelta(minutes=5)
            await prisma.message.create(
                data={
                    "runId": run_id,
                    "role": "user",
                    "content": "stuff",
                    "sequence": 0,
                    "createdAt": recent,
                }
            )
            for i in range(3):
                await prisma.message.create(
                    data={
                        "runId": run_id,
                        "role": "system",
                        "content": f"Resume attempt {i + 1}/3.",
                        "stepType": "resume_attempt",
                        "sequence": i + 1,
                        "createdAt": recent,
                    }
                )

            with patch.object(research_module, "_spawn_run") as spawn_mock:
                await research_module.resume_orphaned_runs()

            spawned_run_ids = [call.args[0] for call in spawn_mock.call_args_list]
            assert run_id not in spawned_run_ids, (
                "a run already at the max resume-attempt count must not be resumed again"
            )

            updated = await prisma.researchrun.find_unique(where={"id": run_id})
            assert updated.status == "failed"
        finally:
            await _cleanup(run_ids=[run_id] if run_id else [], user_emails=[email])

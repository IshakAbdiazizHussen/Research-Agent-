"""Feature 4 (Research Run API & Streaming Progress) integration tests.

Runs against the real app (real lifespan, real Postgres, real checkpointer,
real Redis) via httpx against the ASGI app directly — but the OpenAI SDK
calls are mocked (same approach as test_cache.py) so these tests exercise
the real API/DB/SSE/checkpointer plumbing without live network cost or
non-determinism. Feature 2's own live tests already prove the graph itself
works against the real OpenAI API; these tests are about the route layer.
"""

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from openai.resources.chat.completions.completions import AsyncCompletions
from openai.resources.responses.responses import AsyncResponses

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
    headers = {"X-Dev-User-Email": f"user-a-{uuid.uuid4()}@test.local"}

    async with lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            create_resp = await client.post("/research", json={"query": query}, headers=headers)
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


async def test_stream_of_another_users_run_is_not_found(mocked_openai):
    query = f"integration test query {uuid.uuid4()}"
    owner_headers = {"X-Dev-User-Email": f"owner-{uuid.uuid4()}@test.local"}
    other_headers = {"X-Dev-User-Email": f"other-{uuid.uuid4()}@test.local"}

    async with lifespan(app):
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

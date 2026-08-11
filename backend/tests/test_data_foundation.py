"""Feature 1 (User Identity & Data Foundation) smoke tests.

Runs against the local dev Postgres database configured in backend/.env —
per docs/constraints.md, only local/throwaway dev databases are touched by
automated tests, never a shared/staging/production one.
"""

import uuid

from prisma import Json

from app.db import prisma_client
from app.main import app, lifespan


async def test_lifespan_connects_and_disconnects_prisma():
    assert not prisma_client.prisma.is_connected()
    async with lifespan(app):
        assert prisma_client.prisma.is_connected()
    assert not prisma_client.prisma.is_connected()


async def test_crud_round_trip_for_every_model():
    email = f"smoke-test-{uuid.uuid4()}@local.test"

    async with lifespan(app):
        client = prisma_client.prisma

        user = await client.user.create(data={"email": email})
        assert user.id
        assert user.email == email

        run = await client.researchrun.create(
            data={
                "userId": user.id,
                "query": "what are the current best practices for X?",
            }
        )
        assert run.status == "pending"
        assert run.retryCount == 0

        message = await client.message.create(
            data={
                "runId": run.id,
                "role": "assistant",
                "content": "retrieving sources...",
                "stepType": "retrieving",
                "sequence": 1,
            }
        )
        assert message.stepType == "retrieving"

        checkpoint = await client.checkpoint.create(
            data={"threadId": run.id, "checkpointData": Json({"state": "example"})}
        )
        assert checkpoint.threadId == run.id

        fetched_run = await client.researchrun.find_unique(
            where={"id": run.id},
            include={"messages": True, "checkpoints": True},
        )
        assert fetched_run is not None
        assert fetched_run.userId == user.id
        assert len(fetched_run.messages) == 1
        assert len(fetched_run.checkpoints) == 1

        # Clean up so the dev DB doesn't accumulate smoke-test rows.
        await client.checkpoint.delete(where={"id": checkpoint.id})
        await client.message.delete(where={"id": message.id})
        await client.researchrun.delete(where={"id": run.id})
        await client.user.delete(where={"id": user.id})

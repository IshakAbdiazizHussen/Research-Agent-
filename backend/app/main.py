"""FastAPI entrypoint (Feature 1: User Identity & Data Foundation).

Feature 1 only wires up the data layer's lifecycle (Prisma connect/disconnect)
and logging. Route mounting (POST /research, GET /research/{id}/stream)
belongs to Feature 4 — see docs/development_plan.md.
"""

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

from app.agent.graph import run_research
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db import prisma_client

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_settings()  # fail fast at startup if required env vars are missing
    await prisma_client.connect()
    logger.info("prisma client connected")
    try:
        yield
    finally:
        await prisma_client.disconnect()
        logger.info("prisma client disconnected")


app = FastAPI(title="Research Agent API", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "db_connected": prisma_client.prisma.is_connected()}


# --- THROWAWAY, dev-only ---------------------------------------------------
# Not part of Feature 4's real API (POST /research, GET /research/{id}/stream)
# and intentionally not documented in architecture.md/development_plan.md —
# exists only to exercise agent.graph.run_research() from the browser
# (/docs) while Feature 3's caching is being verified manually. Delete this
# whole block once Feature 4 builds the real endpoint.
if get_settings().environment == "development":

    class _DevTestResearchRequest(BaseModel):
        query: str

    @app.post("/dev/test-research")
    async def dev_test_research(payload: _DevTestResearchRequest) -> dict:
        start = time.perf_counter()
        final_state = await run_research(payload.query)
        elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
        return {**final_state, "elapsed_ms": elapsed_ms}

"""FastAPI entrypoint (Feature 1: User Identity & Data Foundation).

Feature 1 only wires up the data layer's lifecycle (Prisma connect/disconnect)
and logging. Route mounting (POST /research, GET /research/{id}/stream)
belongs to Feature 4 — see docs/development_plan.md.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

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

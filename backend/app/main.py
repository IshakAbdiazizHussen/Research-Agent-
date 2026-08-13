"""FastAPI entrypoint (Feature 1: User Identity & Data Foundation; routes
mounted by Feature 4: Research Run API & Streaming Progress).
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent import checkpointer as agent_checkpointer
from app.api.routes.research import resume_orphaned_runs
from app.api.routes.research import router as research_router
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
    await agent_checkpointer.connect()
    await resume_orphaned_runs()
    try:
        yield
    finally:
        await agent_checkpointer.disconnect()
        await prisma_client.disconnect()
        logger.info("prisma client disconnected")


app = FastAPI(title="Research Agent API", lifespan=lifespan)

# Feature 6 (Frontend Research UI): the Next.js dev server runs on a
# different origin (:3000 vs :8000), so the browser blocks fetch()/SSE
# calls to this API without CORS headers. Origins come from settings, not
# hardcoded (docs/core/config.py's own rule) — see cors_allowed_origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_allowed_origins_list,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Dev-User-Email"],
)

app.include_router(research_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "db_connected": prisma_client.prisma.is_connected()}

"""FastAPI entrypoint (Feature 1: User Identity & Data Foundation; routes
mounted by Feature 4: Research Run API & Streaming Progress).
"""

import logging
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.agent import checkpointer as agent_checkpointer
from app.api.routes.research import resume_orphaned_runs
from app.api.routes.research import router as research_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.db import prisma_client

configure_logging()
logger = logging.getLogger(__name__)

# Development-only CORS policy: any http://localhost:<port> or
# http://127.0.0.1:<port>, not a fixed allow-list — see the decision log
# in docs/architecture.md ("CORS allowed origins") for the full history.
# A fixed list of exact origins kept breaking every time the dev frontend
# landed on a port other than the ones hardcoded (stray leftover
# processes from an earlier restart, Next.js silently falling back to the
# next free port instead of erroring, etc.) — each incident required a
# fresh investigation to even find out which origin had changed. Matching
# any port on these two hostnames survives that by construction, instead
# of chasing one port at a time. This is a fixed application policy
# constant, not environment-tunable config (core/config.py's "everything
# comes from settings" rule is about deployment-specific values — a
# database URL, a model name — not this), so it lives here rather than in
# Settings; it also must NEVER be used outside development, enforced
# below by branching on settings.is_production, not by anything in this
# pattern itself.
_DEV_CORS_ORIGIN_PATTERN = r"^http://(localhost|127\.0\.0\.1):\d+$"
_dev_cors_origin_regex = re.compile(_DEV_CORS_ORIGIN_PATTERN)


def _is_allowed_origin(origin: str, settings: Settings) -> bool:
    """The same allow/deny decision CORSMiddleware itself makes below —
    duplicated here (not imported from Starlette) only so the rejection
    logger can classify an origin without depending on internals of a
    third-party middleware. Driven from the exact same two inputs
    (cors_allowed_origins_list / _dev_cors_origin_regex) as the
    CORSMiddleware configuration itself, so the two can't drift apart."""
    if settings.is_production:
        return origin in settings.cors_allowed_origins_list
    return bool(_dev_cors_origin_regex.fullmatch(origin))


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()  # fail fast at startup if required env vars are missing
    # Logged plainly at every startup, not just inferred from source — a
    # real CORS incident (docs/architecture.md decision log) needed this:
    # the .env-vs-default question is unambiguous from a source read, but
    # "what is the *running* process actually using right now" isn't,
    # especially with `--reload` and long-lived dev sessions.
    if settings.is_production:
        logger.info(
            "CORS mode: fixed allow-list (production) — origins=%s",
            settings.cors_allowed_origins_list,
        )
    else:
        logger.info(
            "CORS mode: regex (development) — any origin matching %r",
            _DEV_CORS_ORIGIN_PATTERN,
        )
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

_settings = get_settings()

# Feature 6 (Frontend Research UI): the Next.js dev server runs on a
# different origin than the backend, so the browser blocks fetch()/SSE
# calls without CORS headers.
#
# Production keeps the original fixed allow_origins list — the permissive
# regex path must NEVER apply outside local dev (settings.is_production
# gates it below, not anything in the pattern itself): "any port on
# localhost/127.0.0.1" is meaningless, and unsafe to reason about, once
# this isn't running on a developer's own machine.
if _settings.is_production:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_settings.cors_allowed_origins_list,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Dev-User-Email"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=_DEV_CORS_ORIGIN_PATTERN,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Dev-User-Email"],
    )


@app.middleware("http")
async def log_rejected_cors_origins(request: Request, call_next):
    """Diagnostic only — makes its own independent allow/deny judgement
    call (_is_allowed_origin) purely to decide whether to log; it never
    blocks or allows the request itself, CORSMiddleware above alone owns
    that. Runs for every request with an Origin header, not just OPTIONS
    preflights, so a rejected simple request is caught too. Exists so a
    future "CORS is failing" incident is visible in one log line instead
    of needing another investigation from scratch (docs/architecture.md
    decision log, "CORS allowed origins" — this is a direct response to
    how much repeat investigation that took)."""
    origin = request.headers.get("origin")
    if origin and not _is_allowed_origin(origin, _settings):
        logger.warning("CORS: rejected origin %r (did not match the active CORS policy)", origin)
    return await call_next(request)


app.include_router(research_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "db_connected": prisma_client.prisma.is_connected()}

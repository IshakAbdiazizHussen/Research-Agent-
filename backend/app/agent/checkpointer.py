"""Postgres-backed LangGraph checkpointer (Feature 4: Research Run API &
Streaming Progress).

Uses LangGraph's official `langgraph-checkpoint-postgres` package rather
than a hand-rolled saver against our own `Checkpoint` Prisma model — chosen
explicitly (with the user's sign-off) over the custom-against-Prisma
alternative, since the official implementation correctly handles LangGraph's
checkpoint protocol (versioning, pending writes) rather than risking subtle
resume bugs. Tradeoff, noted at the same time: this needs its own raw
`psycopg` connection pool (separate from Prisma's connection) and manages
its own tables (`checkpoints`, `checkpoint_writes`, `checkpoint_blobs`) via
its own `.setup()`, created directly in Postgres, outside Prisma's migration
tracking. `schema.prisma`'s `Checkpoint` model is consequently unused by
this feature — left in place, not deleted, without separate sign-off.

NAME COLLISION, discovered and fixed here (reported to the user, not fixed
silently): LangGraph's official saver names its own table `checkpoints` —
the exact same name our `Checkpoint` Prisma model maps to via
`@@map("checkpoints")`. Its first `setup()` run failed with
`UndefinedColumn: column "thread_id" does not exist`, because it found our
*existing*, differently-shaped table (`threadId`, camelCase, our columns)
and tried to migrate it rather than create its own. Fix: LangGraph's tables
now live in their own dedicated Postgres schema (`langgraph_checkpoints`,
created here if missing), set via `search_path` on its connections, so they
never touch `public.checkpoints` (our Prisma table) at all.
"""

import logging

import psycopg
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_LANGGRAPH_SCHEMA = "langgraph_checkpoints"

# Recommended connection kwargs per langgraph-checkpoint-postgres's own docs,
# plus a dedicated search_path so its tables land in their own schema, never
# colliding with our Prisma-managed `public.checkpoints` table (see above).
_CONNECTION_KWARGS = {
    "autocommit": True,
    "prepare_threshold": 0,
    "options": f"-c search_path={_LANGGRAPH_SCHEMA},public",
}

_pool: AsyncConnectionPool | None = None
_saver: AsyncPostgresSaver | None = None


async def connect() -> AsyncPostgresSaver:
    """Open the connection pool, run the checkpointer's own one-time table
    setup, and return the shared saver instance. Call once at app startup;
    safe to call again (idempotent) — returns the existing saver."""
    global _pool, _saver
    if _saver is not None:
        return _saver

    settings = get_settings()

    # Create the dedicated schema first, on a plain connection with no
    # search_path override — must exist before any pooled connection tries
    # to resolve search_path=langgraph_checkpoints.
    async with await psycopg.AsyncConnection.connect(
        settings.database_url, autocommit=True
    ) as setup_conn:
        await setup_conn.execute(f"CREATE SCHEMA IF NOT EXISTS {_LANGGRAPH_SCHEMA}")

    _pool = AsyncConnectionPool(
        conninfo=settings.database_url,
        max_size=20,
        kwargs=_CONNECTION_KWARGS,
        open=False,
    )
    await _pool.open()

    _saver = AsyncPostgresSaver(_pool)
    await _saver.setup()
    logger.info("postgres checkpointer connected and set up")
    return _saver


async def disconnect() -> None:
    global _pool, _saver
    if _pool is not None:
        await _pool.close()
    _pool = None
    _saver = None
    logger.info("postgres checkpointer disconnected")


def get_checkpointer() -> AsyncPostgresSaver:
    """Access the already-connected saver (call connect() first, at app
    startup — this does not lazily connect, so a missing connect() call
    fails loudly instead of silently reconnecting mid-request)."""
    if _saver is None:
        raise RuntimeError(
            "Postgres checkpointer not connected — call "
            "app.agent.checkpointer.connect() during app startup first."
        )
    return _saver

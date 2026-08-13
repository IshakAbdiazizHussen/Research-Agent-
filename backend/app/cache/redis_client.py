"""Redis cache client (Feature 3: Retrieval & LLM Result Caching).

Connection setup plus get_cached()/set_cached() — the only interface any
caller touches (docs/development_plan.md, Feature 3 Guidelines: "No node
or tool touches the Redis client directly"). Every operation here is
wrapped so a Redis error degrades to a cache miss rather than propagating —
a cache failure must never fail the request (docs/constraints.md's Redis
section: "a cache miss and a cache failure are always non-fatal").
"""

import hashlib
import json
import logging
from typing import Any

import redis.asyncio as redis

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

# TTLs per docs/constraints.md's Redis table — the single source of truth,
# not re-typed at each call site (docs/development_plan.md Guidelines).
RETRIEVAL_TTL_SECONDS = 60 * 60  # 1 hour — retrieval:{query_hash}
LLM_TTL_SECONDS = 24 * 60 * 60  # 24 hours — llm:{prompt_hash}

_client: "redis.Redis | None" = None


def _get_client(settings: Settings) -> "redis.Redis":
    global _client
    if _client is None:
        _client = redis.from_url(settings.redis_url, decode_responses=True)
    return _client


def hash_key(*parts: str) -> str:
    """Stable hash of one or more strings, used to build cache keys like
    retrieval:{query_hash} / llm:{prompt_hash} — never the raw query/prompt
    text itself as the key (docs/constraints.md data handling rules)."""
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode("utf-8"))
        digest.update(b"\x00")  # separator so ("ab","c") != ("a","bc")
    return digest.hexdigest()


async def get_cached(key: str, *, settings: Settings | None = None) -> Any | None:
    """Return the cached value for `key`, or None on a miss OR any Redis
    failure — callers can't distinguish the two, by design: both mean
    "perform the live call" (docs/constraints.md)."""
    settings = settings or get_settings()
    try:
        client = _get_client(settings)
        raw = await client.get(key)
    except Exception:
        logger.warning(
            "cache get failed for key=%s; degrading to live call", key, exc_info=True
        )
        return None

    if raw is None:
        return None

    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("cache value for key=%s was not valid JSON; treating as a miss", key)
        return None


async def set_cached(
    key: str, value: Any, ttl_seconds: int, *, settings: Settings | None = None
) -> None:
    """Best-effort cache write. Never raises — a failed write just means the
    next read is a miss, which is safe (docs/constraints.md)."""
    settings = settings or get_settings()
    try:
        client = _get_client(settings)
        await client.set(key, json.dumps(value), ex=ttl_seconds)
    except Exception:
        logger.warning(
            "cache set failed for key=%s; continuing without caching", key, exc_info=True
        )

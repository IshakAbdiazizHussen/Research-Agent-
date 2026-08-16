"""Redis cache client (Feature 3: Retrieval & LLM Result Caching).

Connection setup plus get_cached()/set_cached() — the only interface any
caller touches (docs/development_plan.md, Feature 3 Guidelines: "No node
or tool touches the Redis client directly"). Every operation here is
wrapped so a Redis error degrades to a cache miss rather than propagating —
a cache failure must never fail the request (docs/constraints.md's Redis
section: "a cache miss and a cache failure are always non-fatal").

Also owns the two POST /research enforcement counters added by the
post-launch audit (docs/architecture.md decision log): the per-IP rate
limiter and the system-wide daily cost ceiling. Neither is "caching" in
the Feature 3 sense, but both are counters that live in Redis for the same
reason the cache does — `constraints.md` explicitly names this module as
"the natural place to maintain that counter" for the cost ceiling, and the
rate limiter follows the same reasoning. Same fail-open contract as
get_cached()/set_cached() above, extended here by explicit sign-off (not
assumed): a Redis outage degrades enforcement to "allow the request,
log loudly" rather than blocking traffic — see check_rate_limit() and
get_daily_cost()'s docstrings.
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

# Rate limiting (POST /research only — docs/architecture.md decision log
# "POST /research rate limiting + cost ceiling enforcement"). Fixed window,
# keyed by client IP: 10 requests per IP comfortably covers a real person
# trying the demo (each run already takes 8-20s server-side per
# constraints.md's latency targets, so a human naturally paces well under
# this) while cutting a scripted hammer off almost immediately.
RATE_LIMIT_MAX_REQUESTS = 10
RATE_LIMIT_WINDOW_SECONDS = 10 * 60  # 10 minutes

# Daily cost ceiling ($30/day hard stop — docs/constraints.md "Cost
# ceilings"). RUN_COST_RESERVATION_USD reuses constraints.md's own
# worst-case-per-query figure ($4.28/day worst case ÷ 100 queries/day ≈
# $0.0428/query, every retriever call hitting the 4-call retry cap),
# rounded up to $0.05 to absorb the grader/rewriter/synthesizer/embedding
# calls the doc calls "negligible" without pretending they're exactly
# zero — not a newly invented estimate. WEB_SEARCH_COST_PER_CALL_USD is
# the doc's own $10.00/1,000-calls rate, used at run-completion to true up
# the reservation against the run's real retry_count (see
# api/routes/research.py's _run_graph_and_persist).
DAILY_COST_CEILING_USD = 30.00
RUN_COST_RESERVATION_USD = 0.05
WEB_SEARCH_COST_PER_CALL_USD = 0.01
_DAILY_COST_KEY_TTL_SECONDS = 48 * 60 * 60  # self-cleaning; UTC date is baked into the key

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


async def check_rate_limit(
    client_ip: str, *, settings: Settings | None = None
) -> tuple[bool, int | None]:
    """Fixed-window rate-limit check for one client IP against
    `ratelimit:research:{client_ip}` (RATE_LIMIT_MAX_REQUESTS per
    RATE_LIMIT_WINDOW_SECONDS). Returns (allowed, retry_after_seconds) —
    `retry_after_seconds` is only meaningful when `allowed` is False.

    Fails OPEN on any Redis error (allowed=True, retry_after=None) — a
    Redis outage must not take down POST /research entirely, same
    reasoning as get_cached()'s cache-miss degradation, extended here to
    enforcement by explicit confirmation (docs/architecture.md decision
    log). Unlike a routine cache-miss warning, this is logged at ERROR —
    "loudly", per that confirmation — since it means rate limiting is
    silently not happening, which is worth someone noticing."""
    settings = settings or get_settings()
    key = f"ratelimit:research:{client_ip}"
    try:
        client = _get_client(settings)
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, RATE_LIMIT_WINDOW_SECONDS)
    except Exception:
        logger.error(
            "rate limit check failed (Redis unavailable) for ip=%s — failing open, "
            "request allowed without rate limiting",
            client_ip,
            exc_info=True,
        )
        return True, None

    if count <= RATE_LIMIT_MAX_REQUESTS:
        return True, None

    try:
        ttl = await client.ttl(key)
    except Exception:
        ttl = None
    retry_after = ttl if ttl and ttl > 0 else RATE_LIMIT_WINDOW_SECONDS
    return False, retry_after


def _daily_cost_key(utc_date: str) -> str:
    return f"cost:daily:{utc_date}"


async def get_daily_cost(utc_date: str, *, settings: Settings | None = None) -> float | None:
    """Running total spend (USD) recorded so far for `utc_date`
    (YYYY-MM-DD) — 0.0 if nothing's been recorded yet today, or None if
    Redis itself is unreachable. Callers MUST treat None as fail-open
    (skip the ceiling check, allow the request) — same contract as
    check_rate_limit() above, same explicit sign-off it's built on."""
    settings = settings or get_settings()
    try:
        client = _get_client(settings)
        raw = await client.get(_daily_cost_key(utc_date))
        return float(raw) if raw is not None else 0.0
    except Exception:
        logger.error(
            "daily cost read failed (Redis unavailable) for date=%s — failing open, "
            "cost ceiling not enforced for this request",
            utc_date,
            exc_info=True,
        )
        return None


async def adjust_daily_cost(
    utc_date: str, delta_usd: float, *, settings: Settings | None = None
) -> None:
    """Adjusts `cost:daily:{utc_date}` by `delta_usd` — positive to reserve
    a run's worst-case cost before it starts, negative to true that
    reservation down to the run's real cost once known (see
    api/routes/research.py's _run_graph_and_persist). Best-effort: never
    raises. A failure here means today's tracked total may now
    under-count real spend until the next successful write — logged
    loudly (ERROR, not the routine-miss WARNING level elsewhere in this
    file) since that's a real, if temporary, gap in the $30/day trip-wire,
    not a harmless cache miss."""
    settings = settings or get_settings()
    key = _daily_cost_key(utc_date)
    try:
        client = _get_client(settings)
        await client.incrbyfloat(key, delta_usd)
        await client.expire(key, _DAILY_COST_KEY_TTL_SECONDS)
    except Exception:
        logger.error(
            "daily cost adjust (delta=%.4f) failed (Redis unavailable) for date=%s — "
            "today's tracked spend may now be inaccurate",
            delta_usd,
            utc_date,
            exc_info=True,
        )

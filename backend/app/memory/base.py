"""Long-term memory interface (Feature 5: Long-Term Memory & Past Run
Retrieval) — the swappable one. Every caller (nodes, routes, tests) goes
through `get_memory_store()` and the `MemoryStore` interface only; nothing
outside this file and the concrete `*_store.py` implementations may import
`in_memory_store.py`/`pgvector_store.py` directly (docs/development_plan.md
Guidelines), so the backend stays swappable per docs/architecture.md's
decision log.
"""

from abc import ABC, abstractmethod
from typing import Any, TypedDict

from app.core.config import Settings, get_settings


class MemoryResult(TypedDict):
    text: str
    metadata: dict[str, Any]
    score: float


class MemoryStore(ABC):
    @abstractmethod
    async def store(self, user_id: str, text: str, metadata: dict[str, Any]) -> None: ...

    @abstractmethod
    async def search(self, user_id: str, query: str, top_k: int = 5) -> list[MemoryResult]: ...


_store: MemoryStore | None = None


def get_memory_store(settings: Settings | None = None) -> MemoryStore:
    """The single place backend selection happens — do not hardcode a
    specific store choice anywhere else (docs/development_plan.md
    Guidelines). Cached: the same store instance is reused across calls."""
    global _store
    if _store is not None:
        return _store

    settings = settings or get_settings()
    backend = settings.memory_backend

    if backend == "in_memory":
        from app.memory.in_memory_store import InMemoryStore

        _store = InMemoryStore()
    elif backend == "pgvector":
        # Not built speculatively — only when architecture.md's decision
        # log trigger condition is actually met (docs/development_plan.md
        # Implementation step 3).
        raise NotImplementedError(
            "memory_backend='pgvector' is not implemented yet — "
            "memory/pgvector_store.py doesn't exist."
        )
    else:
        raise ValueError(f"Unknown memory_backend: {backend!r}")

    return _store


def _set_store_for_testing(store: MemoryStore | None) -> None:
    """Test-only hook (docs/development_plan.md QA: "swapping the
    configured backend... requires no changes outside memory/base.py's
    callers' configuration"). Swaps the active store directly rather than
    via settings, so a test can prove callers never need to change without
    also inventing a second real backend just to prove the point. Not used
    by application code."""
    global _store
    _store = store

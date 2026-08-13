"""In-memory long-term memory backend (Feature 5: Long-Term Memory & Past
Run Retrieval) — the default v1 backend, no new infrastructure required
(docs/development_plan.md Implementation step 2).

"In-memory" describes storage, not search quality: entries are still real
OpenAI embeddings (agent/llm_client.embed()), compared by cosine similarity,
so search() is genuine semantic search — just held in a plain Python dict
rather than a vector database. Lost on process restart; that trade-off is
what makes this the dev/prototype backend (docs/architecture.md's tree),
not the final choice (see architecture.md's decision log for pgvector/
Qdrant's trigger condition).
"""

import math
from dataclasses import dataclass
from typing import Any

from app.agent.llm_client import embed
from app.memory.base import MemoryResult, MemoryStore


@dataclass
class _Entry:
    text: str
    metadata: dict[str, Any]
    embedding: list[float]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class InMemoryStore(MemoryStore):
    def __init__(self) -> None:
        # Scoped per user_id at the top level — search() only ever looks
        # inside the requesting user's own list, so it structurally cannot
        # return another customer's entries (docs/development_plan.md
        # Security), not just by convention.
        self._entries: dict[str, list[_Entry]] = {}

    async def store(self, user_id: str, text: str, metadata: dict[str, Any]) -> None:
        embedding = await embed(text)
        self._entries.setdefault(user_id, []).append(
            _Entry(text=text, metadata=metadata, embedding=embedding)
        )

    async def search(self, user_id: str, query: str, top_k: int = 5) -> list[MemoryResult]:
        entries = self._entries.get(user_id, [])
        if not entries:
            return []

        query_embedding = await embed(query)
        scored = [
            MemoryResult(
                text=entry.text,
                metadata=entry.metadata,
                score=_cosine_similarity(query_embedding, entry.embedding),
            )
            for entry in entries
        ]
        scored.sort(key=lambda result: result["score"], reverse=True)
        return scored[:top_k]

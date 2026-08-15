"""Feature 5 (Long-Term Memory & Past Run Retrieval) tests.

test_semantic_search_* makes real OpenAI embedding calls (no mocking) —
deliberately, since the QA bar is "returns the stored entry for a
semantically similar query" (not an identical one), which a mock can't
prove. Embedding calls are cheap (see docs/constraints.md cost ceilings).
test_swapping_backend_* needs no network calls at all.
"""

import uuid
from typing import Any

from app.memory.base import MemoryResult, MemoryStore, _set_store_for_testing, get_memory_store


# TODO(flaky, not yet fixed): this test intermittently fails only when the
# full suite runs together (psycopg_pool.PoolClosed / "Event loop is
# closed") even though it does no Postgres access itself — the error
# belongs to an unrelated unawaited background task from another test.
# Working hypothesis and candidate fixes: docs/constraints.md, "Known
# test-suite flakes (not yet fixed)". Don't re-diagnose from scratch.
async def test_semantic_search_finds_similar_entry_and_scopes_to_user():
    store = get_memory_store()
    user_a = f"user-a-{uuid.uuid4()}"
    user_b = f"user-b-{uuid.uuid4()}"

    await store.store(
        user_a,
        "The Eiffel Tower was completed in 1889 and stands in Paris, France.",
        {"run_id": "run-1"},
    )
    await store.store(
        user_b,
        "Photosynthesis converts sunlight, water, and carbon dioxide into glucose.",
        {"run_id": "run-2"},
    )

    # Semantically related, textually different from the stored summary.
    results = await store.search(user_a, "When was the famous Paris landmark tower built?")
    assert results, "expected at least one match for a semantically similar query"
    assert "Eiffel Tower" in results[0]["text"]
    assert results[0]["metadata"]["run_id"] == "run-1"
    assert results[0]["score"] > 0.3  # genuinely similar, not a coincidence

    # user_b's search must never return user_a's entry, even though it
    # exists and would score highly against an unrelated query embedding
    # if scoping were broken.
    b_results = await store.search(user_b, "When was the famous Paris landmark tower built?")
    assert all(r["metadata"]["run_id"] != "run-1" for r in b_results)

    # A brand-new user with nothing stored gets an empty list, not an error.
    empty_results = await store.search(f"user-c-{uuid.uuid4()}", "anything")
    assert empty_results == []


async def test_swapping_backend_requires_no_caller_changes():
    """Proves memory/base.py's callers (get_memory_store().store()/.search())
    never need to change when the backend does — only the factory's
    internal wiring does (docs/development_plan.md QA)."""

    class _StubMemoryStore(MemoryStore):
        def __init__(self) -> None:
            self.stored: list[tuple[str, str, dict[str, Any]]] = []

        async def store(self, user_id: str, text: str, metadata: dict[str, Any]) -> None:
            self.stored.append((user_id, text, metadata))

        async def search(self, user_id: str, query: str, top_k: int = 5) -> list[MemoryResult]:
            return [MemoryResult(text="stub result", metadata={}, score=1.0)]

    stub = _StubMemoryStore()
    _set_store_for_testing(stub)
    try:
        # Identical call pattern any real caller (api/routes/research.py)
        # already uses — no special-casing for the stub.
        await get_memory_store().store("user-x", "some text", {"k": "v"})
        results = await get_memory_store().search("user-x", "some query")
    finally:
        _set_store_for_testing(None)  # restore the real configured backend

    assert stub.stored == [("user-x", "some text", {"k": "v"})]
    assert results == [{"text": "stub result", "metadata": {}, "score": 1.0}]

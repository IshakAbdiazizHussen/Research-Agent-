"""Feature 3 (Retrieval & LLM Result Caching) tests.

The LLM/web-search *calls* are mocked here (unlike test_agent_graph.py) —
these tests are about the caching layer's behavior (does a second identical
call skip the live call? does a Redis outage degrade gracefully?), not
about search/LLM correctness, so there's no reason to spend real API money
re-proving that. A real local Redis (backend/.env's REDIS_URL) is used,
since Redis is free and testing against the real cache backend is what
actually gives confidence here.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import app.cache.redis_client as cache_mod
from app.agent.llm_client import complete
from app.cache.redis_client import get_cached, hash_key, set_cached
from app.core.config import get_settings
from app.tools.web_search_openai import OpenAIWebSearchTool


async def test_get_set_cached_round_trip():
    key = f"test:{uuid.uuid4()}"
    assert await get_cached(key) is None  # genuinely nothing cached yet

    await set_cached(key, {"hello": "world"}, ttl_seconds=60)
    assert await get_cached(key) == {"hello": "world"}


async def test_web_search_tool_second_call_is_a_cache_hit():
    query = f"cache test query {uuid.uuid4()}"
    fake_response = SimpleNamespace()  # no `output` attr -> zero results, fine

    with patch(
        "app.tools.web_search_openai._get_client"
    ) as get_client:
        get_client.return_value.responses.create = AsyncMock(return_value=fake_response)

        tool = OpenAIWebSearchTool()
        first = await tool.run(query)
        second = await tool.run(query)

        assert first == second == []
        # The whole point: only ONE live call for two identical queries.
        assert get_client.return_value.responses.create.call_count == 1


async def test_llm_complete_second_call_is_a_cache_hit():
    system_prompt = "You are a test."
    user_prompt = f"cache test prompt {uuid.uuid4()}"
    fake_message = SimpleNamespace(content="cached answer")
    fake_choice = SimpleNamespace(message=fake_message)
    fake_response = SimpleNamespace(choices=[fake_choice])

    with patch("app.agent.llm_client._get_client") as get_client:
        get_client.return_value.chat.completions.create = AsyncMock(
            return_value=fake_response
        )

        first = await complete(system_prompt, user_prompt)
        second = await complete(system_prompt, user_prompt)

        assert first == second == "cached answer"
        assert get_client.return_value.chat.completions.create.call_count == 1


async def test_cache_degrades_gracefully_on_redis_failure():
    """A cache miss and a cache failure both look the same to the caller:
    None back from get_cached, a no-op from set_cached — never an
    exception (docs/constraints.md)."""
    settings = get_settings()
    broken_settings = settings.model_copy(update={"redis_url": "redis://localhost:1/0"})

    # Reset the module-level client singleton so it actually picks up the
    # broken URL instead of reusing an already-connected working client.
    cache_mod._client = None
    try:
        result = await get_cached("any-key", settings=broken_settings)
        assert result is None  # degraded to a miss, no exception raised

        await set_cached("any-key", "value", ttl_seconds=60, settings=broken_settings)
        # No assertion needed beyond "didn't raise" — that's the contract.
    finally:
        cache_mod._client = None  # don't leave later tests pointed at a dead client


async def test_web_search_tool_falls_back_to_live_call_on_redis_failure():
    """End-to-end: if Redis is down, the tool must still return a correct
    result via a live call, not fail the request."""
    query = f"redis-down test query {uuid.uuid4()}"
    fake_response = SimpleNamespace()

    settings = get_settings()
    broken_settings = settings.model_copy(update={"redis_url": "redis://localhost:1/0"})

    cache_mod._client = None
    try:
        with patch("app.tools.web_search_openai._get_client") as get_client:
            get_client.return_value.responses.create = AsyncMock(return_value=fake_response)

            tool = OpenAIWebSearchTool(settings=broken_settings)
            result = await tool.run(query)

            assert result == []  # correct result despite Redis being unreachable
            assert get_client.return_value.responses.create.call_count == 1
    finally:
        cache_mod._client = None


def test_hash_key_is_stable_and_distinguishes_inputs():
    assert hash_key("a", "b") == hash_key("a", "b")
    assert hash_key("a", "b") != hash_key("ab")
    assert hash_key("a", "b") != hash_key("a", "c")

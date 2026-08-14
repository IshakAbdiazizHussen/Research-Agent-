"""Feature 7 (Evaluation & Quality Harness) tests.

Tests the eval runner's own scoring logic against a tiny, fully-mocked
fixture (docs/development_plan.md QA: "confirm scoring logic is correct
before trusting it on the full eval set") — no live API calls, no cost, no
non-determinism. This is deliberately NOT a run against the real
eval_set.json; that's tests/eval/run_eval.py, invoked manually/separately.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from openai.resources.chat.completions.completions import AsyncCompletions
from openai.resources.responses.responses import AsyncResponses

from tests.eval.run_eval import EvalResult, compute_metrics, run_one_eval


def _mock_openai(*, citations: int, grader_verdict: str, judge_verdict: str, answer: str):
    """Builds fake responses.create()/chat.completions.create() functions
    for one controlled fixture case. citations=0 simulates OpenAI's real,
    documented "no sources found" behavior (see architecture.md's decision
    log) — every retriever attempt returns zero citations, so the graph
    exhausts its retry cap, exactly like the real failure mode this
    project has already traced and accepted."""

    def fake_responses_create(*args, **kwargs):
        if citations == 0:
            return SimpleNamespace(output=[])
        annotations = [
            SimpleNamespace(
                type="url_citation",
                url=f"https://example.com/{i}",
                title=f"Source {i}",
                start_index=0,
                end_index=10,
            )
            for i in range(citations)
        ]
        content_part = SimpleNamespace(text="x" * 50, annotations=annotations)
        return SimpleNamespace(output=[SimpleNamespace(type="message", content=[content_part])])

    def fake_chat_completions_create(*args, **kwargs):
        messages = kwargs.get("messages", [])
        system_content = messages[0]["content"] if messages else ""

        if "grading whether a retrieved web document" in system_content:
            content = grader_verdict
        elif "grading a research assistant" in system_content:
            content = judge_verdict
        elif "rewrite research questions" in system_content:
            content = "rewritten query"
        else:
            content = answer

        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    return fake_responses_create, fake_chat_completions_create


async def test_eval_scoring_against_a_known_fixture():
    # Case 1: sources found, grader accepts them, judge says correct,
    # converges without hitting the retry cap.
    resp_fn, chat_fn = _mock_openai(
        citations=2,
        grader_verdict="relevant",
        judge_verdict="correct",
        answer="Good answer [1][2].",
    )
    with patch.object(AsyncResponses, "create", AsyncMock(side_effect=resp_fn)), \
         patch.object(AsyncCompletions, "create", AsyncMock(side_effect=chat_fn)):
        result_1 = await run_one_eval("fixture question one", "reference one")

    assert result_1.grounded is True
    assert result_1.judged_correct is True
    assert result_1.hit_retry_cap is False

    # Case 2: sources found, but the judge says the answer doesn't
    # actually match the reference.
    resp_fn, chat_fn = _mock_openai(
        citations=2,
        grader_verdict="relevant",
        judge_verdict="incorrect",
        answer="Wrong answer [1][2].",
    )
    with patch.object(AsyncResponses, "create", AsyncMock(side_effect=resp_fn)), \
         patch.object(AsyncCompletions, "create", AsyncMock(side_effect=chat_fn)):
        result_2 = await run_one_eval("fixture question two", "reference two")

    assert result_2.grounded is True
    assert result_2.judged_correct is False

    # Case 3: zero citations on every attempt (the real, documented OpenAI
    # web_search failure mode) — never grounded, exhausts the retry cap.
    resp_fn, chat_fn = _mock_openai(
        citations=0,
        grader_verdict="irrelevant",
        judge_verdict="incorrect",
        answer="No sources available.",
    )
    with patch.object(AsyncResponses, "create", AsyncMock(side_effect=resp_fn)), \
         patch.object(AsyncCompletions, "create", AsyncMock(side_effect=chat_fn)):
        result_3 = await run_one_eval("fixture question three", "reference three")

    assert result_3.grounded is False
    assert result_3.hit_retry_cap is True

    metrics = compute_metrics([result_1, result_2, result_3])
    assert metrics["total"] == 3
    assert metrics["groundedness_rate"] == pytest.approx(2 / 3)
    assert metrics["judged_correct_rate"] == pytest.approx(1 / 3)
    assert metrics["retry_cap_exhaustion_rate"] == pytest.approx(1 / 3)


def test_compute_metrics_edge_cases():
    assert compute_metrics([]) == {
        "groundedness_rate": 0.0,
        "judged_correct_rate": 0.0,
        "retry_cap_exhaustion_rate": 0.0,
        "total": 0,
    }

    all_good = [
        EvalResult(
            question="q",
            expected_answer="e",
            actual_answer="a",
            grounded=True,
            judged_correct=True,
            hit_retry_cap=False,
            retry_count=0,
        )
        for _ in range(4)
    ]
    metrics = compute_metrics(all_good)
    assert metrics["groundedness_rate"] == 1.0
    assert metrics["judged_correct_rate"] == 1.0
    assert metrics["retry_cap_exhaustion_rate"] == 0.0

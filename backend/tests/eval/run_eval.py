"""Evaluation & Quality Harness (Feature 7).

Operationalizes project_definition.md's success criteria into a repeatable,
scored check against backend/tests/eval/eval_set.json. Not part of the
served application — a manually-invoked tool, run after any node/prompt
change (docs/development_plan.md Implementation step 4: "documented manual
command" chosen over wiring into CI, since this makes real, billed OpenAI
calls per question, and CI-triggered spend on every push/PR isn't something
to take on silently).

Usage (from backend/, with the venv active):
    python -m tests.eval.run_eval
    python -m tests.eval.run_eval --eval-set path/to/other_set.json

Security (docs/development_plan.md Feature 7): calls agent.graph.
run_research() directly — the same ephemeral, non-checkpointed entrypoint
test_agent_graph.py already uses (docs/architecture.md Guidelines: "not
through the HTTP layer, to keep the eval fast and isolated from API/auth
concerns"). This never touches Postgres and never calls
get_memory_store().store() — there is no ResearchRun/Message row and no
long-term-memory entry for any eval question, by construction, not by a
separate namespacing convention bolted on after the fact. It also runs
against the same OPENAI_API_KEY as everything else in this project — there
is no separate non-production credential/quota to switch to yet (single-
environment dev setup); noting that honestly rather than claiming isolation
this project doesn't actually have.
"""

import argparse
import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from app.agent.graph import MAX_RETRIES, run_research
from app.agent.llm_client import complete

_DEFAULT_EVAL_SET_PATH = Path(__file__).parent / "eval_set.json"

# LLM-judge prompt — verbatim from docs/development_plan.md; do not edit
# here without updating that doc. Used only by this eval harness, never by
# the production graph.
_JUDGE_SYSTEM_PROMPT = """You are grading a research assistant's answer against a reference
answer. Score "correct" only if the answer's key claims match the
reference answer's key claims and are supported by cited sources. Score
"incorrect" otherwise, including partially right-but-misleading answers."""

_JUDGE_USER_PROMPT_TEMPLATE = """Question: {query}
Reference answer: {expected_answer}
Assistant's answer (with sources): {actual_answer}

Respond with only one word: "correct" or "incorrect"."""


@dataclass
class EvalResult:
    question: str
    expected_answer: str
    actual_answer: str | None
    grounded: bool  # at least one cited source present — a simple proxy
    # for project_definition.md's "at least one valid, relevant cited
    # source per key claim"; this checks presence, not per-claim validity,
    # which would need claim-level extraction this harness doesn't do.
    judged_correct: bool
    hit_retry_cap: bool  # retry_count reached MAX_RETRIES
    retry_count: int


def _format_answer_with_sources(answer: str | None, sources: list[dict]) -> str:
    if not answer:
        return "(no answer produced)"
    if not sources:
        return answer
    numbered = "\n".join(
        f"[{i}] {s.get('title', '')} ({s.get('url', '')})" for i, s in enumerate(sources, 1)
    )
    return f"{answer}\n\nSources:\n{numbered}"


async def judge_answer(query: str, expected_answer: str, actual_answer_with_sources: str) -> bool:
    """The LLM-judge from docs/development_plan.md's Feature 7 Prompts
    section. Returns True only for a "correct" verdict — anything else
    (including a malformed/unexpected response) fails closed, not open."""
    verdict = await complete(
        _JUDGE_SYSTEM_PROMPT,
        _JUDGE_USER_PROMPT_TEMPLATE.format(
            query=query,
            expected_answer=expected_answer,
            actual_answer=actual_answer_with_sources,
        ),
    )
    return verdict.strip().lower().startswith("correct")


async def run_one_eval(question: str, expected_answer: str) -> EvalResult:
    final_state = await run_research(question)
    answer = final_state.get("answer")
    sources = final_state.get("sources") or []
    retry_count = final_state.get("retry_count", 0)

    actual_with_sources = _format_answer_with_sources(answer, sources)
    correct = await judge_answer(question, expected_answer, actual_with_sources)

    return EvalResult(
        question=question,
        expected_answer=expected_answer,
        actual_answer=answer,
        grounded=len(sources) > 0,
        judged_correct=correct,
        hit_retry_cap=retry_count >= MAX_RETRIES,
        retry_count=retry_count,
    )


async def run_eval_set(eval_set_path: Path = _DEFAULT_EVAL_SET_PATH) -> list[EvalResult]:
    questions = json.loads(eval_set_path.read_text())
    results = []
    for item in questions:
        result = await run_one_eval(item["question"], item["expected_answer"])
        results.append(result)
    return results


def compute_metrics(results: list[EvalResult]) -> dict[str, float]:
    """Pure function, no I/O — the three eval-facing metrics from
    docs/project_definition.md's success criteria, computed from already-
    collected EvalResults. Kept separate from run_eval_set() specifically
    so it's unit-testable against synthetic data with zero API calls
    (docs/development_plan.md QA: scoring logic verified against a tiny
    fixture before trusting it on the full eval set)."""
    total = len(results)
    if total == 0:
        return {
            "groundedness_rate": 0.0,
            "judged_correct_rate": 0.0,
            "retry_cap_exhaustion_rate": 0.0,
            "total": 0,
        }

    return {
        "groundedness_rate": sum(r.grounded for r in results) / total,
        "judged_correct_rate": sum(r.judged_correct for r in results) / total,
        "retry_cap_exhaustion_rate": sum(r.hit_retry_cap for r in results) / total,
        "total": total,
    }


def _print_report(results: list[EvalResult], metrics: dict[str, float]) -> None:
    print(f"\n{'=' * 80}\nEval results ({metrics['total']} questions)\n{'=' * 80}")
    for r in results:
        flags = []
        if not r.grounded:
            flags.append("NO SOURCES")
        if not r.judged_correct:
            flags.append("JUDGED INCORRECT")
        if r.hit_retry_cap:
            flags.append("HIT RETRY CAP")
        status = ", ".join(flags) if flags else "OK"
        print(f"  [{status}] {r.question}")

    print(f"\n{'=' * 80}\nMetrics (docs/project_definition.md success criteria)\n{'=' * 80}")
    print(f"  Groundedness rate:          {metrics['groundedness_rate']:.0%}  (target: >= 80%)")
    print(f"  Judged-correct rate:        {metrics['judged_correct_rate']:.0%}  (target: >= 80%)")
    print(
        f"  Retry-cap-exhaustion rate:  {metrics['retry_cap_exhaustion_rate']:.0%}  "
        f"(target: <= 5%, i.e. >= 95% converge without exhausting the cap)"
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run the research agent eval harness.")
    parser.add_argument(
        "--eval-set",
        type=Path,
        default=_DEFAULT_EVAL_SET_PATH,
        help="Path to a question/expected_answer JSON file (default: tests/eval/eval_set.json).",
    )
    args = parser.parse_args()

    results = await run_eval_set(args.eval_set)
    metrics = compute_metrics(results)
    _print_report(results, metrics)


if __name__ == "__main__":
    asyncio.run(main())

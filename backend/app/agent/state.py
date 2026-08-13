"""Graph state schema (Feature 2: Core Research Agent Graph).

All nodes read/write only this typed state — no hidden globals
(docs/development_plan.md, Feature 2 Guidelines). Field set matches the
Implementation section of Feature 2 exactly: query, search_query,
retrieved_docs, graded_docs, retry_count, answer, sources, status.

`status` mirrors the Prisma `RunStatus` enum values (docs/architecture.md,
backend/app/db/prisma/schema.prisma) so Feature 4 can copy it straight onto
`ResearchRun.status` without translation.
"""

from typing import TypedDict


class RetrievedDoc(TypedDict):
    """One web-search result (docs/architecture.md: tools/web_search_openai.py)."""

    title: str
    url: str
    content: str


class GradedDoc(RetrievedDoc):
    """A retrieved doc plus the grader's relevance judgement."""

    relevant: bool


class Source(TypedDict):
    """A citation attached to the synthesized answer (docs/architecture.md:
    ResearchRun.sources — {url, title, snippet})."""

    url: str
    title: str
    snippet: str


class AgentState(TypedDict):
    query: str
    search_query: str
    retrieved_docs: list[RetrievedDoc]
    graded_docs: list[GradedDoc]
    retry_count: int
    answer: str | None
    sources: list[Source]
    status: str

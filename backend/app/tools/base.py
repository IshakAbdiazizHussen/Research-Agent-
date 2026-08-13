"""Tool interface (Feature 2: Core Research Agent Graph).

Every tool a node calls goes through this interface — no node makes a raw
HTTP call inline (docs/development_plan.md, Feature 2 Guidelines). Keeping
the interface this small is what makes a provider swap (e.g. a different
web-search API) a new class here, not a change to any node.
"""

from abc import ABC, abstractmethod
from typing import Any


class Tool(ABC):
    name: str

    @abstractmethod
    async def run(self, input: Any) -> Any:
        """Execute the tool and return its result. Implementations should
        raise on failure rather than return a sentinel — callers decide how
        to handle errors (docs/constraints.md's degrade-gracefully policy is
        specific to the cache layer, Feature 3, not tool calls themselves)."""
        ...

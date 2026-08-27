"""AIPP AI executor boundary.

Routes a task to the deterministic model router and executes through an
injected provider adapter. Network access and credentials remain outside the
core; tests can supply a local adapter.
"""
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from ai.model_router import ModelSpec, route


class ProviderAdapter(Protocol):
    def execute(self, model: ModelSpec, task: Mapping[str, Any]) -> Any:
        """Execute a task with the selected model."""


@dataclass(frozen=True)
class ExecutionResult:
    provider: str
    model: str
    output: Any


def execute(task: Mapping[str, Any], adapter: ProviderAdapter) -> ExecutionResult:
    """Select a model from task capabilities and delegate execution."""
    selected = route(task.get("capabilities", ()))
    output = adapter.execute(selected, task)
    return ExecutionResult(selected.provider, selected.model, output)

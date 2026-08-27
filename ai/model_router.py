from dataclasses import dataclass
from typing import FrozenSet, Iterable


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    model: str
    capabilities: FrozenSet[str]
    priority: int
    enabled: bool = True


class RoutingError(RuntimeError):
    pass


DEFAULT_MODELS = (
    ModelSpec("gemini", "pro", frozenset({"text", "code", "reasoning"}), 100),
    ModelSpec("claude", "sonnet", frozenset({"text", "code", "reasoning"}), 90),
    ModelSpec("gemini", "flash", frozenset({"text", "code", "fast"}), 80),
)


def route(required_capabilities: Iterable[str], registry=DEFAULT_MODELS) -> ModelSpec:
    required = frozenset(required_capabilities)
    candidates = [
        model for model in registry
        if model.enabled and required.issubset(model.capabilities)
    ]
    if not candidates:
        raise RoutingError(f"No enabled model matches capabilities: {sorted(required)}")
    return max(candidates, key=lambda model: model.priority)

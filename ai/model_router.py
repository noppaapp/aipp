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
    # Semantic workspace analysis is intentionally Flash-first: it is the
    # high-volume pass. Pro and Claude remain fallbacks for harder/failed calls.
    ModelSpec("gemini", "flash", frozenset({"text", "code", "reasoning", "fast"}), 100),
    ModelSpec("gemini", "pro", frozenset({"text", "code", "reasoning"}), 90),
    ModelSpec("claude", "sonnet", frozenset({"text", "code", "reasoning"}), 80),
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

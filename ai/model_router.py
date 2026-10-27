from dataclasses import dataclass
from typing import FrozenSet, Iterable


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    model: str
    capabilities: FrozenSet[str]
    priority: int
    enabled: bool = True


DEFAULT_MODELS = (
    # Keep Gemini first. If both Gemini variants fail (including quota errors),
    # try Groq, then OpenRouter, and finally Claude when configured.
    ModelSpec("gemini", "flash", frozenset({"text", "code", "reasoning", "fast"}), 100),
    ModelSpec("gemini", "pro", frozenset({"text", "code", "reasoning"}), 90),
    ModelSpec("groq", "llama-3.3-70b-versatile", frozenset({"text", "code", "reasoning", "fast"}), 85),
    ModelSpec("openrouter", "openrouter/free", frozenset({"text", "code", "reasoning", "fast"}), 80),
    ModelSpec("claude", "sonnet", frozenset({"text", "code", "reasoning"}), 70),
)


class RoutingError(RuntimeError):
    pass


def route(required_capabilities: Iterable[str], registry=DEFAULT_MODELS) -> ModelSpec:
    required = frozenset(required_capabilities)
    candidates = [
        model for model in registry
        if model.enabled and required.issubset(model.capabilities)
    ]
    if not candidates:
        raise RoutingError(f"No enabled model matches capabilities: {sorted(required)}")
    return max(candidates, key=lambda model: model.priority)

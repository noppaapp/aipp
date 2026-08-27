"""Deterministic AI provider/model routing for AIPP.

This module selects an executor from declared task capabilities. It does not
perform network calls and never stores credentials. Live provider execution is
intentionally outside this registry.
"""
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    model: str
    capabilities: frozenset[str]
    priority: int = 100
    enabled: bool = True


DEFAULT_MODELS: tuple[ModelSpec, ...] = (
    ModelSpec("gemini", "flash", frozenset({"text", "code", "fast"}), 10),
    ModelSpec("gemini", "pro", frozenset({"text", "code", "reasoning"}), 20),
    ModelSpec("claude", "sonnet", frozenset({"text", "code", "reasoning"}), 30),
    ModelSpec("openai", "general", frozenset({"text", "code", "reasoning"}), 40),
)


class RoutingError(ValueError):
    """Raised when no enabled model can satisfy a task capability set."""


def route(required_capabilities: Iterable[str], registry: Iterable[ModelSpec] = DEFAULT_MODELS) -> ModelSpec:
    required = frozenset(required_capabilities)
    candidates = [m for m in registry if m.enabled and required.issubset(m.capabilities)]
    if not candidates:
        raise RoutingError(f"No enabled model satisfies capabilities: {sorted(required)}")
    return min(candidates, key=lambda m: (m.priority, m.provider, m.model))

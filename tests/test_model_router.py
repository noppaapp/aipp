import pytest

from ai.model_router import DEFAULT_MODELS, RoutingError, ModelSpec, route


def test_routes_by_capability_and_priority():
    selected = route({"code", "fast"})
    assert selected.provider == "gemini"
    assert selected.model == "flash"


def test_reasoning_route_is_deterministic():
    selected = route({"code", "reasoning"})
    assert selected.provider == "gemini"
    assert selected.model == "pro"


def test_disabled_model_is_not_selected():
    registry = tuple(
        ModelSpec(m.provider, m.model, m.capabilities, m.priority, False) if m.model == "pro" else m
        for m in DEFAULT_MODELS
    )
    selected = route({"code", "reasoning"}, registry)
    assert selected.provider == "claude"


def test_no_capability_match_fails_closed():
    with pytest.raises(RoutingError):
        route({"vision"}, DEFAULT_MODELS)

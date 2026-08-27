from ai.executor import execute
from ai.model_router import ModelSpec


class FakeAdapter:
    def __init__(self):
        self.calls = []

    def execute(self, model: ModelSpec, task):
        self.calls.append((model, task))
        return "ok"


def test_executor_routes_and_delegates():
    adapter = FakeAdapter()
    result = execute({"capabilities": {"code", "fast"}, "input": "x"}, adapter)

    assert result.provider == "gemini"
    assert result.model == "flash"
    assert result.output == "ok"
    assert len(adapter.calls) == 1


def test_executor_keeps_provider_call_outside_core():
    adapter = FakeAdapter()
    task = {"capabilities": {"code", "reasoning"}, "input": "x"}
    result = execute(task, adapter)

    assert result.provider == "gemini"
    assert result.model == "pro"
    assert adapter.calls[0][1] is task

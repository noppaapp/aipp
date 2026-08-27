import pytest

from runtime.continuation import ContinuationHalt, continue_verified


def test_continuation_stops_after_verified_success():
    calls = []

    def execute(task):
        calls.append("execute")
        return task + 1

    def verify(task):
        return task == 2

    result = continue_verified(0, execute, verify, max_attempts=3)

    assert result.result == 2
    assert result.attempts == 2
    assert calls == ["execute", "execute"]


def test_continuation_retries_then_halts_at_bound():
    calls = []

    def execute(task):
        calls.append(1)
        return task

    with pytest.raises(ContinuationHalt):
        continue_verified("task", execute, lambda _: False, max_attempts=3)

    assert len(calls) == 3


def test_continuation_rejects_invalid_bound():
    with pytest.raises(ValueError):
        continue_verified("task", lambda x: x, lambda _: True, max_attempts=0)

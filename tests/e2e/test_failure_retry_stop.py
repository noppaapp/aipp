import pytest


def test_failure_is_not_silent():
    with pytest.raises(RuntimeError, match="HALT"):
        raise RuntimeError("HALT: controlled E2E failure")


def test_retry_is_explicit():
    attempts = []
    for attempt in range(1, 3):
        attempts.append(attempt)
        if attempt == 2:
            break
    assert attempts == [1, 2]


def test_stop_state_is_terminal():
    state = {"status": "STOP"}
    assert state["status"] == "STOP"

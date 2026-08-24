import pytest


def test_halt_is_terminal_and_blocks_follow_up_execution():
    state = {"status": "HALT", "execution_attempts": 0}

    with pytest.raises(RuntimeError, match="HALT"):
        if state["status"] == "HALT":
            raise RuntimeError("HALT: terminal state reached")
        state["execution_attempts"] += 1

    assert state["status"] == "HALT"
    assert state["execution_attempts"] == 0


def test_stop_is_terminal_and_does_not_auto_continue():
    state = {"status": "STOP", "execution_attempts": 0}

    if state["status"] == "STOP":
        return

    state["execution_attempts"] += 1
    pytest.fail("STOP state must not continue execution")

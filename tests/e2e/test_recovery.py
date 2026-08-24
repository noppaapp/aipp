from pathlib import Path

import aipp_runner


def test_failed_verification_preserves_executable_state(tmp_path):
    workspace = tmp_path
    (workspace / "AIPP.md").write_text("# AIPP\n", encoding="utf-8")
    (workspace / "PROJECT_BOOT.md").write_text("# BOOT\n", encoding="utf-8")

    state = aipp_runner.default_state()
    task = {
        "id": "RECOVERY-001",
        "title": "Recovery validation",
        "status": "APPROVED",
    }
    state["task_lifecycle"]["NOW"] = task

    state = aipp_runner.execute_task(state, workspace)
    artifact = workspace / task["artifact"]
    artifact.unlink()

    try:
        aipp_runner.verify_task(state, workspace)
        raise AssertionError("verification should have halted")
    except RuntimeError as exc:
        assert str(exc).startswith("HALT:")

    assert state["status"] == "EXECUTED"
    assert state["task_lifecycle"]["NOW"]["status"] == "EXECUTED"

    aipp_runner.save_json(artifact, {
        "task_id": "RECOVERY-001",
        "title": "Recovery validation",
        "execution_mode": "REAL",
        "runner": state["runner_engine"],
        "result": "EXECUTED",
    })
    state = aipp_runner.verify_task(state, workspace)
    assert state["status"] == "COMPLETED"
    assert state["task_lifecycle"]["NOW"] is None

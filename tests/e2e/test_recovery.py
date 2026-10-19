from pathlib import Path

import aipp_runner
from aipp_authority import binding_digest


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
    task["binding_digest"] = binding_digest(task)
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

    # A legacy artifact without an action mode must not be accepted as proof.
    aipp_runner.save_json(artifact, {
        "task_id": "RECOVERY-001",
        "title": "Recovery validation",
        "execution_mode": "REAL",
        "runner": state["runner_engine"],
        "result": "EXECUTED",
    })
    try:
        aipp_runner.verify_task(state, workspace)
        raise AssertionError("legacy artifact should have halted verification")
    except RuntimeError as exc:
        assert str(exc) == "HALT: Artifact verification failed"

    # A correctly labelled local artifact can be verified, but not auto-completed.
    aipp_runner.save_json(artifact, {
        "task_id": "RECOVERY-001",
        "title": "Recovery validation",
        "execution_mode": "REAL",
        "action_mode": "LOCAL_ONLY",
        "runner": state["runner_engine"],
        "result": "LOCAL_ARTIFACT_CREATED",
    })
    state = aipp_runner.verify_task(state, workspace)
    assert state["status"] == "AWAITING_COMPLETION_AUTHORITY"
    assert state["task_lifecycle"]["NOW"]["status"] == "VERIFIED"
    assert state["task_lifecycle"]["COMPLETED"] == []

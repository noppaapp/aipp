from pathlib import Path

import aipp_runner
from aipp_authority import proposal_id


def authority_text(pid, task_id):
    return (
        "# AUTHORITY_LOG\n\n"
        "| Proposal ID | Task ID | Decision | Timestamp | Note |\n"
        "| :--- | :--- | :--- | :--- | :--- |\n"
        f"| {pid} | {task_id} | APPROVED | 2026-08-26T00:00:00Z | human |\n"
    )


def test_real_execution_lifecycle_is_deterministic_and_ephemeral(tmp_path):
    (tmp_path / "AIPP.md").write_text("# AIPP\n", encoding="utf-8")
    (tmp_path / "PROJECT_BOOT.md").write_text(
        "# PROJECT_BOOT: AIPP\n\n"
        "**Workspace Status:** ACTIVE\n"
        "**Active State:** [READY]\n\n"
        "| Task ID | Task Description | Status | Dependency / Reason |\n"
        "| :--- | :--- | :--- | :--- |\n"
        "| **EXECUTION-001** | `Real execution lifecycle proof` | `FUTURE` | - |\n",
        encoding="utf-8",
    )

    state = aipp_runner.initialize_state(aipp_runner.default_state(), str(tmp_path))
    state = aipp_runner.request_approval(state, "EXECUTION-001")

    task = next(task for task in state["task_lifecycle"]["FUTURE"] if task["id"] == "EXECUTION-001")
    pid = proposal_id(task)
    state = aipp_runner.approve_task(state, "EXECUTION-001", authority_text(pid, "EXECUTION-001"))

    assert state["status"] == "NOW"
    assert state["task_lifecycle"]["NOW"]["status"] == "APPROVED"

    state = aipp_runner.execute_task(state, tmp_path)
    artifact = tmp_path / state["task_lifecycle"]["NOW"]["artifact"]
    assert artifact.exists()
    assert state["status"] == "EXECUTED"

    state = aipp_runner.verify_task(state, tmp_path)
    assert state["status"] == "COMPLETED"
    assert state["task_lifecycle"]["NOW"] is None
    assert state["task_lifecycle"]["COMPLETED"][0]["id"] == "EXECUTION-001"
    assert not (tmp_path / "aipp_state.json").exists()

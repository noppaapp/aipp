import base64
import json
import os
from pathlib import Path

from aipp_authority import proposal_id
from aipp_runner import approve_task, continue_execution, default_state, initialize_state, request_approval

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "external_action_task.json"


def test_runner_executes_real_external_github_action(tmp_path):
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    (tmp_path / "AIPP.md").write_text("# AIPP\n", encoding="utf-8")
    (tmp_path / "PROJECT_BOOT.md").write_text(
        "# PROJECT_BOOT: AIPP\n\n"
        "**Workspace Status:** ACTIVE\n"
        "**Active State:** [READY]\n\n"
        "| Task ID | Task Description | Status | Dependency / Reason |\n"
        "| :--- | :--- | :--- | :--- |\n"
        f"| **{fixture['id']}** | `{fixture['title']}` | `FUTURE` | - |\n",
        encoding="utf-8",
    )

    state = initialize_state(default_state(), tmp_path)
    task = state["task_lifecycle"]["FUTURE"][0]
    task["external_action"] = fixture["external_action"]

    approval = (
        "| Proposal ID | Task ID | Decision | Timestamp |\n"
        "| :--- | :--- | :--- | :--- |\n"
        f"| {proposal_id(task)} | {task['id']} | APPROVED | 2026-08-27T00:00:00Z |\n"
    )
    env = os.environ.copy()
    env["AIPP_AUTHORITY_LOG_B64"] = base64.b64encode(approval.encode("utf-8")).decode("ascii")
    old_env = os.environ.get("AIPP_AUTHORITY_LOG_B64")
    os.environ["AIPP_AUTHORITY_LOG_B64"] = env["AIPP_AUTHORITY_LOG_B64"]
    try:
        state = request_approval(state, task["id"])
        state = approve_task(state, task["id"])
        state = continue_execution(state, tmp_path)
    finally:
        if old_env is None:
            os.environ.pop("AIPP_AUTHORITY_LOG_B64", None)
        else:
            os.environ["AIPP_AUTHORITY_LOG_B64"] = old_env

    assert state["status"] == "COMPLETED"
    completed = state["task_lifecycle"]["COMPLETED"][0]
    assert completed["id"] == task["id"]
    artifact = json.loads((tmp_path / completed["artifact"]).read_text(encoding="utf-8"))
    assert artifact["external_result"]["action"] == "GITHUB_PROOF_BRANCH"
    assert artifact["external_result"]["verified"] is True
    assert not (tmp_path / "aipp_state.json").exists()

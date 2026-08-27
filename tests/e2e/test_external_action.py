import base64
import json
import os
import subprocess
import sys
from pathlib import Path

from aipp_authority import proposal_id

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "aipp_runner.py"
FIXTURE = ROOT / "tests" / "external_action_task.json"


def test_runner_executes_real_external_github_action(tmp_path):
    task = json.loads(FIXTURE.read_text(encoding="utf-8"))
    (tmp_path / "AIPP.md").write_text("# AIPP\n", encoding="utf-8")
    (tmp_path / "PROJECT_BOOT.md").write_text(
        "# PROJECT_BOOT: AIPP\n\n"
        "**Workspace Status:** ACTIVE\n"
        "**Active State:** [READY]\n\n"
        "| Task ID | Task Description | Status | Dependency / Reason |\n"
        "| :--- | :--- | :--- | :--- |\n"
        f"| **{task['id']}** | `{task['title']}` | `FUTURE` | - |\n",
        encoding="utf-8",
    )

    approval = (
        "| Proposal ID | Task ID | Decision | Timestamp |\n"
        "| :--- | :--- | :--- | :--- |\n"
        f"| {proposal_id(task)} | {task['id']} | APPROVED | 2026-08-27T00:00:00Z |\n"
    )
    env = os.environ.copy()
    env["AIPP_AUTHORITY_LOG_B64"] = base64.b64encode(approval.encode("utf-8")).decode("ascii")

    result = subprocess.run(
        [sys.executable, str(RUNNER), "CONTINUE", "--workspace", str(tmp_path), "--task", task["id"]],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        env=env,
        check=True,
    )

    state = json.loads(result.stdout)
    assert state["status"] == "COMPLETED"
    completed = state["task_lifecycle"]["COMPLETED"][0]
    assert completed["id"] == task["id"]
    artifact = json.loads((tmp_path / completed["artifact"]).read_text(encoding="utf-8"))
    assert artifact["external_result"]["action"] == "GITHUB_PROOF_BRANCH"
    assert artifact["external_result"]["verified"] is True
    assert not (tmp_path / "aipp_state.json").exists()

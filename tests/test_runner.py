import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "aipp_runner.py"


def run(command, task=None, cwd=ROOT):
    args = [sys.executable, str(RUNNER), command, "--workspace", str(cwd)]
    if task:
        args += ["--task", task]
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=True)


def write_boot(path, task_status="FUTURE"):
    (path / "AIPP.md").write_text("# test\n", encoding="utf-8")
    (path / "PROJECT_BOOT.md").write_text(
        "# PROJECT_BOOT: AIPP\n\n"
        "**Workspace Status:** ACTIVE\n"
        "**Active State:** [READY]\n\n"
        "| Task ID | Task Description | Status | Dependency / Reason |\n"
        "| :--- | :--- | :--- | :--- |\n"
        f"| **TASK-01** | `Execution proof` | `{task_status}` | - |\n",
        encoding="utf-8",
    )


def test_bootstrap_is_ephemeral(tmp_path):
    write_boot(tmp_path)
    result = run("BAŞLA", cwd=tmp_path)
    state = json.loads(result.stdout)

    assert state["active_project"] == "AIPP"
    assert state["task_lifecycle"]["FUTURE"][0]["id"] == "TASK-01"
    assert not (tmp_path / "aipp_state.json").exists()


def test_authority_gate_does_not_persist_across_sessions(tmp_path):
    write_boot(tmp_path)
    result = run("REQUEST_APPROVAL", "TASK-01", cwd=tmp_path)
    state = json.loads(result.stdout)
    assert state["status"] == "AWAITING_AUTHORITY"
    assert state["authority_gate"]["pending_approval"] == "TASK-01"
    assert not (tmp_path / "aipp_state.json").exists()


def test_run_cannot_autonomously_approve(tmp_path):
    write_boot(tmp_path)
    result = subprocess.run(
        [sys.executable, str(RUNNER), "RUN", "--task", "TASK-01", "--workspace", str(tmp_path)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "cannot autonomously approve" in result.stderr
    assert not (tmp_path / "aipp_state.json").exists()

import json
import subprocess
import sys


ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]
RUNNER = ROOT / "aipp_runner.py"


def run(command, workspace, task=None, check=True):
    args = [sys.executable, str(RUNNER), command, "--workspace", str(workspace)]
    if task:
        args += ["--task", task]
    return subprocess.run(args, cwd=workspace, text=True, capture_output=True, check=check)


def write_boot(path):
    (path / "AIPP.md").write_text("# AIPP\n", encoding="utf-8")
    (path / "PROJECT_BOOT.md").write_text(
        "# PROJECT_BOOT: AIPP\n\n"
        "**Workspace Status:** ACTIVE\n"
        "**Active State:** [READY]\n\n"
        "| Task ID | Task Description | Status | Dependency / Reason |\n"
        "| :--- | :--- | :--- | :--- |\n"
        "| **SESSION-001** | `Cross-session continuation proof` | `FUTURE` | - |\n",
        encoding="utf-8",
    )


def test_session_restart_does_not_restore_ephemeral_authority_state(tmp_path):
    """A fresh process must not recover approval from discarded runtime memory."""
    write_boot(tmp_path)

    first = run("REQUEST_APPROVAL", tmp_path, "SESSION-001")
    first_state = json.loads(first.stdout)
    assert first_state["status"] == "AWAITING_AUTHORITY"
    assert first_state["authority_gate"]["pending_approval"] == "SESSION-001"
    assert not (tmp_path / "aipp_state.json").exists()

    second = run("APPROVE", tmp_path, "SESSION-001", check=False)
    assert second.returncode != 0
    assert "canonical Authority Gate transition" in second.stderr
    assert not (tmp_path / "aipp_state.json").exists()


def test_session_restart_reloads_canonical_project_boot(tmp_path):
    """A new process can re-bootstrap from the canonical PROJECT_BOOT.md source."""
    write_boot(tmp_path)

    first = run("BAŞLA", tmp_path)
    first_state = json.loads(first.stdout)
    assert first_state["active_project"] == "AIPP"
    assert first_state["task_lifecycle"]["FUTURE"][0]["id"] == "SESSION-001"

    second = run("BAŞLA", tmp_path)
    second_state = json.loads(second.stdout)
    assert second_state["active_project"] == "AIPP"
    assert second_state["task_lifecycle"]["FUTURE"][0]["id"] == "SESSION-001"
    assert not (tmp_path / "aipp_state.json").exists()

    print("SESSION_CONTINUATION_PROOF: canonical PROJECT_BOOT reloaded; ephemeral authority state was not restored")

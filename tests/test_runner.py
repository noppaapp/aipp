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


def test_authority_gate_does_not_persist_across_sessions(tmp_path, monkeypatch):
    write_boot(tmp_path)
    bootstrap = run("BAŞLA", cwd=tmp_path)
    monkeypatch.setenv("AIPP_SESSION_STATE_B64", __import__("base64").b64encode(bootstrap.stdout.encode()).decode())
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

def test_runner_creates_passive_next_proposal_from_explicit_proof_signal(tmp_path):
    write_boot(tmp_path, task_status="COMPLETED")
    (tmp_path / "AIPP_EXECUTION_PROOF.md").write_text(
        "# AIPP Execution Proof\\n\\nStatus: PROOF_REQUESTED\\n", encoding="utf-8"
    )

    result = run("BAŞLA", cwd=tmp_path)
    state = json.loads(result.stdout)

    assert state["status"] == "PROPOSAL_READY"
    assert state["task_lifecycle"]["NOW"] is None
    assert state["task_lifecycle"]["FUTURE"][0]["id"] == "TASK-02"
    assert state["task_lifecycle"]["FUTURE"][0]["status"] == "PROPOSED"
    proposal = state["task_lifecycle"]["FUTURE"][0]
    assert proposal["capability"] == "external_execution_proof"
    assert "github" not in json.dumps(proposal).lower()
    assert state["authority_gate"]["pending_approval"] is None
    assert state["authority_gate"]["last_action"] == "AUTONOMOUS_PROPOSAL_CREATED"


def test_project_intelligence_persists_drive_scan_for_panel_state():
    from aipp_runner import default_state, reconcile_project_intelligence

    intelligence = {
        "version": "2",
        "engine": "deterministic-evidence-reconciliation",
        "documents_scanned": 15,
        "findings": [{"type": "near_duplicate"}],
        "proposals": [{"action": "REVIEW", "target": "source"}],
        "drive_scan": {
            "files_scanned": 15,
            "documents_read": 15,
            "documents_unreadable": 0,
            "folders_scanned": 2,
        },
        "semantic": {"enabled": False, "available": False},
    }

    state = reconcile_project_intelligence(default_state(), intelligence)

    assert state["project_intelligence"]["drive_scan"]["files_scanned"] == 15
    assert state["project_intelligence"]["drive_scan"]["documents_read"] == 15
    assert state["project_intelligence"]["documents_scanned"] == 15

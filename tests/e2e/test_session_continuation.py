import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "aipp_runner.py"


def run(command, workspace, task=None):
    args = [sys.executable, str(RUNNER), command, "--workspace", str(workspace)]
    if task:
        args += ["--task", task]
    return subprocess.run(args, cwd=workspace, text=True, capture_output=True, check=True)


def test_session_continuation_survives_process_restart(tmp_path):
    """AIPP must resume from persisted canonical state after the first process ends."""
    (tmp_path / "AIPP.md").write_text("# AIPP\n", encoding="utf-8")
    (tmp_path / "PROJECT_BOOT.md").write_text("# BOOT\n", encoding="utf-8")

    state = {
        "version": "1.1.1",
        "status": "PROPOSAL_READY",
        "active_project": "AIPP",
        "execution_mode": "REAL",
        "task_lifecycle": {
            "NOW": None,
            "DEFERRED": [],
            "BLOCKED": [],
            "FUTURE": [{
                "id": "SESSION-001",
                "title": "Cross-session continuation proof",
                "status": "FUTURE"
            }],
            "REFERENCE": [],
            "COMPLETED": []
        },
        "authority_gate": {"pending_approval": None, "last_action": "INITIALIZATION"},
        "step": 1,
        "runner_engine": "Session Continuation Test"
    }
    state_path = tmp_path / "aipp_state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    # Session 1: request approval, then terminate the process completely.
    run("REQUEST_APPROVAL", tmp_path, "SESSION-001")
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "AWAITING_AUTHORITY"
    assert persisted["authority_gate"]["pending_approval"] == "SESSION-001"

    # Session 2: a fresh process reloads the persisted state and continues.
    run("APPROVE", tmp_path, "SESSION-001")
    run("EXECUTE", tmp_path)
    run("VERIFY", tmp_path)

    final_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert final_state["status"] == "COMPLETED"
    assert final_state["task_lifecycle"]["NOW"] is None
    assert final_state["task_lifecycle"]["COMPLETED"][0]["id"] == "SESSION-001"
    assert final_state["authority_gate"]["last_action"] == "VERIFIED"

    artifact = tmp_path / final_state["task_lifecycle"]["COMPLETED"][0]["artifact"]
    assert artifact.exists()

    print("SESSION_CONTINUATION_PROOF: session-1 persisted state; session-2 resumed and verified")

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


def test_full_execution_cycle(tmp_path):
    (tmp_path / "AIPP.md").write_text("# test\n", encoding="utf-8")
    (tmp_path / "PROJECT_BOOT.md").write_text("# test\n", encoding="utf-8")
    state = {
        "version": "1.1.1",
        "status": "PROPOSAL_READY",
        "active_project": "AIPP",
        "execution_mode": "REAL",
        "task_lifecycle": {
            "NOW": None,
            "DEFERRED": [],
            "BLOCKED": [],
            "FUTURE": [{"id": "AIPP-EXEC-001", "title": "Execution proof", "status": "FUTURE"}],
            "REFERENCE": [],
            "COMPLETED": []
        },
        "authority_gate": {"pending_approval": None, "last_action": "INITIALIZATION"},
        "step": 1,
        "runner_engine": "Test Runner"
    }
    (tmp_path / "aipp_state.json").write_text(json.dumps(state), encoding="utf-8")

    run("RUN", "AIPP-EXEC-001", cwd=tmp_path)
    result = json.loads((tmp_path / "aipp_state.json").read_text(encoding="utf-8"))

    assert result["status"] == "COMPLETED"
    assert result["task_lifecycle"]["NOW"] is None
    assert result["task_lifecycle"]["COMPLETED"][0]["id"] == "AIPP-EXEC-001"
    artifact = tmp_path / result["task_lifecycle"]["COMPLETED"][0]["artifact"]
    assert artifact.exists()


def test_authority_gate_blocks_unknown_task(tmp_path):
    (tmp_path / "AIPP.md").write_text("# test\n", encoding="utf-8")
    (tmp_path / "PROJECT_BOOT.md").write_text("# test\n", encoding="utf-8")
    (tmp_path / "aipp_state.json").write_text(json.dumps({
        "version": "1.1.1", "status": "PROPOSAL_READY", "active_project": "AIPP",
        "execution_mode": "REAL",
        "task_lifecycle": {"NOW": None, "DEFERRED": [], "BLOCKED": [], "FUTURE": [], "REFERENCE": [], "COMPLETED": []},
        "authority_gate": {"pending_approval": None, "last_action": "INITIALIZATION"},
        "step": 1, "runner_engine": "Test Runner"
    }), encoding="utf-8")
    result = subprocess.run([sys.executable, str(RUNNER), "REQUEST_APPROVAL", "--task", "NOPE", "--workspace", str(tmp_path)], cwd=tmp_path, text=True, capture_output=True)
    assert result.returncode != 0
    assert "FUTURE task not found" in result.stderr

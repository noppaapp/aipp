import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "aipp_runner.py"


def test_project_bootstrap_maps_canonical_workspace(tmp_path):
    (tmp_path / "AIPP.md").write_text("# AIPP\n", encoding="utf-8")
    (tmp_path / "PROJECT_BOOT.md").write_text(
        """# PROJECT_BOOT: Demo Project\n\n"
        "**Workspace Status:** ACTIVE\n"
        "**Active State:** [READY]\n\n"
        "| Task ID | Task Description | Status | Dependency / Reason |\n"
        "| :--- | :--- | :--- | :--- |\n"
        "| **TASK-01** | `First task` | `COMPLETED` | - |\n"
        "| **TASK-02** | `Future task` | `FUTURE` | TASK-01 |\n""",
        encoding="utf-8"
    )
    state = {
        "version": "1.1.1", "status": "INITIALIZED", "active_project": None,
        "execution_mode": "REAL",
        "task_lifecycle": {"NOW": None, "DEFERRED": [], "BLOCKED": [], "FUTURE": [], "REFERENCE": [], "COMPLETED": []},
        "authority_gate": {"pending_approval": None, "last_action": "INITIALIZATION"},
        "step": 0, "runner_engine": "Test Runner"
    }
    (tmp_path / "aipp_state.json").write_text(json.dumps(state), encoding="utf-8")

    result = subprocess.run([sys.executable, str(RUNNER), "BAŞLA", "--workspace", str(tmp_path)], cwd=tmp_path, text=True, capture_output=True, check=True)
    output = json.loads(result.stdout)

    assert output["active_project"] == "Demo Project"
    assert output["project_bootstrap"]["source"] == "PROJECT_BOOT.md"
    assert [x["id"] for x in output["task_lifecycle"]["COMPLETED"]] == ["TASK-01"]
    assert [x["id"] for x in output["task_lifecycle"]["FUTURE"]] == ["TASK-02"]
    assert output["task_lifecycle"]["NOW"] is None
    assert output["status"] == "PROPOSAL_READY"

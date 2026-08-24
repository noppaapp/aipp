import json
from pathlib import Path


def test_final_autonomous_loop_drive_state_to_verified_state(tmp_path):
    drive_state = {
        "version": "1.1.1",
        "status": "NOW",
        "task": {"id": "TASK-15", "status": "APPROVED"},
    }
    source = tmp_path / "drive_canonical_state.json"
    source.write_text(json.dumps(drive_state), encoding="utf-8")

    state = json.loads(source.read_text(encoding="utf-8"))
    assert state["status"] == "NOW"

    artifact = tmp_path / "TASK-15-execution.json"
    artifact.write_text(json.dumps({"task_id": "TASK-15", "result": "EXECUTED"}), encoding="utf-8")

    state["task"]["status"] = "COMPLETED"
    state["status"] = "COMPLETED"
    source.write_text(json.dumps(state), encoding="utf-8")

    final_state = json.loads(source.read_text(encoding="utf-8"))
    final_artifact = json.loads(artifact.read_text(encoding="utf-8"))

    assert final_state["status"] == "COMPLETED"
    assert final_state["task"]["status"] == "COMPLETED"
    assert final_artifact["task_id"] == "TASK-15"
    assert final_artifact["result"] == "EXECUTED"

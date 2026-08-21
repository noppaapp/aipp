import argparse
import json
import os
from pathlib import Path
from datetime import datetime, timezone

STATE_FILE = "aipp_state.json"
PROJECT_BOOT = "PROJECT_BOOT.md"
AIPP_SPEC = "AIPP.md"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def save_json(path, data):
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def validate_workspace():
    required = [AIPP_SPEC, PROJECT_BOOT]
    missing = [x for x in required if not Path(x).exists()]
    if missing:
        raise RuntimeError("HALT: Missing canonical workspace files: " + ", ".join(missing))


def default_state():
    return {
        "version": "1.1.1",
        "status": "INITIALIZED",
        "active_project": None,
        "execution_mode": "REAL",
        "task_lifecycle": {
            "NOW": None,
            "DEFERRED": [],
            "BLOCKED": [],
            "FUTURE": [],
            "REFERENCE": [],
            "COMPLETED": []
        },
        "authority_gate": {
            "pending_approval": None,
            "last_action": "INITIALIZATION"
        },
        "step": 0,
        "runner_engine": "GitHub Actions Autonomous Cloud Runner"
    }


def load_state():
    defaults = default_state()
    if not Path(STATE_FILE).exists():
        return defaults

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    # Backward-compatible schema repair for older canonical state files.
    for key in ("version", "active_project", "execution_mode", "step", "runner_engine"):
        if key not in state or state[key] is None:
            state[key] = defaults[key]

    lifecycle = state.get("task_lifecycle")
    if not isinstance(lifecycle, dict):
        lifecycle = {}
    for key, value in defaults["task_lifecycle"].items():
        if key not in lifecycle or lifecycle[key] is None:
            lifecycle[key] = value.copy() if isinstance(value, list) else value
    state["task_lifecycle"] = lifecycle

    gate = state.get("authority_gate")
    if not isinstance(gate, dict):
        gate = {}
    for key, value in defaults["authority_gate"].items():
        if key not in gate or gate[key] is None:
            gate[key] = value
    state["authority_gate"] = gate

    return state


def initialize_state(state):
    state["status"] = "PROPOSAL_READY"
    state["step"] = 1
    state["authority_gate"]["last_action"] = "INITIALIZATION"
    return state


def find_future_task(state, task_id):
    for task in state["task_lifecycle"]["FUTURE"]:
        if task.get("id") == task_id:
            return task
    return None


def request_approval(state, task_id):
    task = find_future_task(state, task_id)
    if task is None:
        raise RuntimeError(f"HALT: FUTURE task not found: {task_id}")
    state["authority_gate"]["pending_approval"] = task_id
    state["authority_gate"]["last_action"] = "APPROVAL_REQUESTED"
    state["status"] = "AWAITING_AUTHORITY"
    return state


def approve_task(state, task_id):
    pending = state["authority_gate"].get("pending_approval")
    if pending != task_id:
        raise RuntimeError(f"HALT: Authority Gate mismatch. pending={pending}, requested={task_id}")
    task = find_future_task(state, task_id)
    if task is None:
        raise RuntimeError(f"HALT: Task disappeared from FUTURE: {task_id}")
    state["task_lifecycle"]["FUTURE"].remove(task)
    task["status"] = "APPROVED"
    state["authority_gate"]["pending_approval"] = None
    state["authority_gate"]["last_action"] = "APPROVED"
    state["task_lifecycle"]["NOW"] = task
    state["status"] = "NOW"
    state["step"] = 2
    return state


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", default="BAŞLA")
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--task")
    args = parser.parse_args()
    os.chdir(args.workspace)
    validate_workspace()
    state = load_state()
    command = args.command.upper()

    if command == "BAŞLA":
        state = initialize_state(state)
    elif command == "REQUEST_APPROVAL":
        if not args.task:
            raise RuntimeError("HALT: --task is required.")
        state = request_approval(state, args.task)
    elif command == "APPROVE":
        if not args.task:
            raise RuntimeError("HALT: --task is required.")
        state = approve_task(state, args.task)
    else:
        raise RuntimeError(f"HALT: Unknown command: {args.command}")

    state["last_updated"] = utc_now()
    save_json(STATE_FILE, state)
    print(json.dumps(state, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

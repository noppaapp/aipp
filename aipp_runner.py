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
    gate = state.get("authority_gate")
    if not isinstance(gate, dict):
        gate = {}
    gate.setdefault("pending_approval", None)
    gate["last_action"] = "INITIALIZATION"
    state["authority_gate"] = gate
    state["status"] = "PROPOSAL_READY"
    state["step"] = 1
    return state


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command")
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--task", default=None)
    args = parser.parse_args()

    os.chdir(args.workspace)
    validate_workspace()
    state = load_state()
    state = initialize_state(state)
    state["last_updated"] = utc_now()
    if args.task:
        state["active_project"] = args.task
    save_json(STATE_FILE, state)
    print(json.dumps(state, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

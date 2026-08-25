import argparse
import base64
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from aipp_project_bootstrap import bootstrap_project_from_text
from aipp_authority import AUTHORITY_LOG, AUTHORITY_ENV, is_approved, proposal_id

AIPP_SPEC = "AIPP.md"
ARTIFACT_DIR = Path("artifacts")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def load_json(path):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Canonical file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    path = Path(path)
    tmp = Path(f"{path}.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    tmp.replace(path)


def validate_workspace():
    if not Path(AIPP_SPEC).exists():
        raise RuntimeError("HALT: Missing AIPP.md protocol specification")


def load_canonical_project_boot(workspace="."):
    boot_path = Path(workspace) / "PROJECT_BOOT.md"
    if boot_path.exists():
        return boot_path.read_text(encoding="utf-8")
    encoded = os.environ.get("AIPP_PROJECT_BOOT_B64", "").strip()
    if encoded:
        try:
            return base64.b64decode(encoded).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise RuntimeError("HALT: Canonical PROJECT_BOOT.md transport is invalid") from exc
    raise RuntimeError("HALT: Canonical PROJECT_BOOT.md was not supplied by Drive runtime")


def load_canonical_authority_log():
    encoded = os.environ.get(AUTHORITY_ENV, "").strip()
    if not encoded:
        return ""
    try:
        return base64.b64decode(encoded).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise RuntimeError("HALT: Canonical AUTHORITY_LOG.md transport is invalid") from exc


def default_state():
    return {
        "version": "1.1.1",
        "status": "INITIALIZED",
        "active_project": None,
        "execution_mode": "REAL",
        "task_lifecycle": {"NOW": None, "DEFERRED": [], "BLOCKED": [], "FUTURE": [], "REFERENCE": [], "COMPLETED": []},
        "authority_gate": {"pending_approval": None, "last_action": "INITIALIZATION"},
        "step": 0,
        "runner_engine": "GitHub Actions Autonomous Cloud Runner",
    }


def load_state():
    return default_state()


def initialize_state(state, workspace):
    state = bootstrap_project_from_text(load_canonical_project_boot(workspace), state)
    state["status"] = "PROPOSAL_READY"
    state["step"] = 1
    state["authority_gate"]["last_action"] = "INITIALIZATION"
    return state


def find_future_task(state, task_id):
    return next((task for task in state["task_lifecycle"].get("FUTURE", []) if task.get("id") == task_id), None)


def request_approval(state, task_id):
    task = find_future_task(state, task_id)
    if task is None:
        raise RuntimeError(f"HALT: FUTURE task not found: {task_id}")
    state["authority_gate"]["pending_approval"] = task_id
    state["authority_gate"]["pending_proposal_id"] = proposal_id(task)
    state["authority_gate"]["last_action"] = "APPROVAL_REQUESTED"
    state["status"] = "AWAITING_AUTHORITY"
    return state


def approve_task(state, task_id, authority_log=None):
    """Apply a canonical Drive approval using only the current session's boot state.

    A previous runtime session is not required. The task and its deterministic
    proposal identity are reconstructed from the current PROJECT_BOOT.md, then
    matched against the canonical AUTHORITY_LOG.md supplied by the Drive runtime.
    """
    task = find_future_task(state, task_id)
    if task is None:
        raise RuntimeError(f"HALT: FUTURE task not found: {task_id}")

    actual_proposal = proposal_id(task)
    pending = state["authority_gate"].get("pending_approval")
    pending_proposal = state["authority_gate"].get("pending_proposal_id")

    # If this process previously requested approval, verify that ephemeral
    # request context has not changed. A fresh process may legitimately have
    # no pending request because runtime memory is intentionally discarded.
    if pending is not None and pending != task_id:
        raise RuntimeError(f"HALT: Authority Gate mismatch. pending={pending}, requested={task_id}")
    if pending_proposal is not None and pending_proposal != actual_proposal:
        raise RuntimeError("HALT: Proposal changed after approval request")

    source = load_canonical_authority_log() if authority_log is None else authority_log
    if not is_approved(source, task):
        raise RuntimeError(f"HALT: canonical Authority Gate transition missing approval: {actual_proposal}")

    state["task_lifecycle"]["FUTURE"].remove(task)
    task["status"] = "APPROVED"
    task["proposal_id"] = actual_proposal
    state["authority_gate"]["pending_approval"] = None
    state["authority_gate"]["pending_proposal_id"] = None
    state["authority_gate"]["last_action"] = "APPROVED"
    state["task_lifecycle"]["NOW"] = task
    state["status"] = "NOW"
    state["step"] = 2
    return state


def execute_task(state, workspace):
    task = state["task_lifecycle"].get("NOW")
    if not task:
        raise RuntimeError("HALT: No task in NOW state")
    if task.get("status") not in {"APPROVED", "NOW"}:
        raise RuntimeError(f"HALT: Task is not executable: {task.get('status')}")
    artifact_dir = Path(workspace) / ARTIFACT_DIR
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / f"{task['id']}-execution.json"
    save_json(artifact_path, {"task_id": task["id"], "title": task.get("title"), "execution_mode": state.get("execution_mode", "REAL"), "executed_at": utc_now(), "runner": state.get("runner_engine"), "result": "EXECUTED"})
    task["status"] = "EXECUTED"
    task["artifact"] = str(artifact_path).replace("\\", "/")
    state["status"] = "EXECUTED"
    state["step"] = 3
    state["authority_gate"]["last_action"] = "EXECUTED"
    return state


def verify_task(state, workspace):
    task = state["task_lifecycle"].get("NOW")
    if not task or task.get("status") != "EXECUTED":
        raise RuntimeError("HALT: No executed task available for verification")
    artifact_path = Path(workspace) / task["artifact"]
    if not artifact_path.exists():
        raise RuntimeError(f"HALT: Expected artifact missing: {artifact_path}")
    artifact = load_json(artifact_path)
    if artifact.get("task_id") != task.get("id") or artifact.get("result") != "EXECUTED":
        raise RuntimeError("HALT: Artifact verification failed")
    task["status"] = "COMPLETED"
    task["verified_at"] = utc_now()
    state["task_lifecycle"]["COMPLETED"].append(task)
    state["task_lifecycle"]["NOW"] = None
    state["status"] = "COMPLETED"
    state["step"] = 4
    state["authority_gate"]["last_action"] = "VERIFIED"
    return state


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", default="BAŞLA")
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--task")
    parser.add_argument("--authority-log", default=AUTHORITY_LOG)
    args = parser.parse_args()
    workspace = Path(args.workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    os.chdir(workspace)
    validate_workspace()
    state = load_state()
    command = args.command.upper()
    if command == "BAŞLA":
        state = initialize_state(state, ".")
    elif command == "REQUEST_APPROVAL":
        if not args.task:
            raise RuntimeError("HALT: --task is required.")
        state = initialize_state(state, ".")
        state = request_approval(state, args.task)
    elif command == "APPROVE":
        if not args.task:
            raise RuntimeError("HALT: --task is required.")
        state = initialize_state(state, ".")
        state = approve_task(state, args.task)
    elif command == "EXECUTE":
        state = execute_task(state, ".")
    elif command == "VERIFY":
        state = verify_task(state, ".")
    elif command == "RUN":
        raise RuntimeError("HALT: RUN cannot autonomously approve a task. Use canonical Authority Gate approval before EXECUTE.")
    else:
        raise RuntimeError(f"HALT: Unknown command: {args.command}")
    state["last_updated"] = utc_now()
    print(json.dumps(state, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

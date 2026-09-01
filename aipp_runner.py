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
from runtime.continuation import ContinuationHalt, continue_verified
from runtime.github_external import ExternalActionHalt, execute_bounded_github_proof
from runtime.github_target import TargetProjectHalt, apply_text_file

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


def load_discovered_candidates():
    encoded = os.environ.get("AIPP_TASK_CANDIDATES_B64", "").strip()
    if not encoded:
        return []
    try:
        value = json.loads(base64.b64decode(encoded).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("HALT: Canonical Drive task discovery transport is invalid") from exc
    if not isinstance(value, list):
        raise RuntimeError("HALT: Canonical Drive task discovery payload is not a list")
    return value


def reconcile_discovered_tasks(state):
    """Merge Drive discovery into the ephemeral FUTURE queue only."""
    lifecycle = state.setdefault("task_lifecycle", {})
    lifecycle.setdefault("FUTURE", [])
    existing = {task.get("id") for task in lifecycle["FUTURE"] if isinstance(task, dict)}
    for candidate in load_discovered_candidates():
        for task_id in candidate.get("task_ids", []):
            if task_id in existing:
                continue
            lifecycle["FUTURE"].append({
                "id": task_id,
                "title": f"Drive-discovered task {task_id}",
                "status": "PROPOSED",
                "dependency_reason": "Discovered in canonical Drive workspace",
                "source": {"file_id": candidate.get("id"), "file_name": candidate.get("name")},
            })
            existing.add(task_id)
    state.setdefault("authority_gate", {})["last_action"] = "WORKSPACE_DISCOVERY_PROPOSALS"
    return state


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
    task = find_future_task(state, task_id)
    if task is None:
        raise RuntimeError(f"HALT: FUTURE task not found: {task_id}")
    actual_proposal = proposal_id(task)
    pending = state["authority_gate"].get("pending_approval")
    pending_proposal = state["authority_gate"].get("pending_proposal_id")
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
    external_result = None
    try:
        if task.get("external_action") == "GITHUB_PROOF_BRANCH":
            external_result = execute_bounded_github_proof(task["id"])
        elif task.get("external_action") == "GITHUB_TARGET_TEXT_FILE":
            external_result = apply_text_file(
                task["id"],
                task.get("target_path", ""),
                task.get("target_content", ""),
                title=task.get("title"),
                body=task.get("description"),
            )
    except (ExternalActionHalt, TargetProjectHalt) as exc:
        raise RuntimeError(str(exc)) from exc
    artifact_dir = Path(workspace) / ARTIFACT_DIR
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / f"{task['id']}-execution.json"
    save_json(artifact_path, {"task_id": task["id"], "title": task.get("title"), "execution_mode": state.get("execution_mode", "REAL"), "executed_at": utc_now(), "runner": state.get("runner_engine"), "external_result": external_result, "result": "EXECUTED"})
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
    if task.get("external_action") == "GITHUB_PROOF_BRANCH":
        external = artifact.get("external_result") or {}
        if external.get("action") != "GITHUB_PROOF_BRANCH" or external.get("verified") is not True:
            raise RuntimeError("HALT: External GitHub action verification failed")
    if task.get("external_action") == "GITHUB_TARGET_TEXT_FILE":
        external = artifact.get("external_result") or {}
        if not external.get("repository") or not external.get("branch") or not external.get("pull_request"):
            raise RuntimeError("HALT: Target project execution verification failed")
    task["status"] = "COMPLETED"
    task["verified_at"] = utc_now()
    state["task_lifecycle"]["COMPLETED"].append(task)
    state["task_lifecycle"]["NOW"] = None
    state["status"] = "COMPLETED"
    state["step"] = 4
    state["authority_gate"]["last_action"] = "VERIFIED"
    return state


def continue_execution(state, workspace, max_attempts=3):
    def execute_step(current):
        return execute_task(current, workspace)

    def verify_step(current):
        task = current["task_lifecycle"].get("NOW")
        if not task or task.get("status") != "EXECUTED":
            return False
        artifact_path = Path(workspace) / task.get("artifact", "")
        if not artifact_path.exists():
            task["status"] = "NOW"
            return False
        artifact = load_json(artifact_path)
        valid = artifact.get("task_id") == task.get("id") and artifact.get("result") == "EXECUTED"
        if task.get("external_action") == "GITHUB_PROOF_BRANCH":
            external = artifact.get("external_result") or {}
            valid = valid and external.get("action") == "GITHUB_PROOF_BRANCH" and external.get("verified") is True
        if task.get("external_action") == "GITHUB_TARGET_TEXT_FILE":
            external = artifact.get("external_result") or {}
            valid = valid and bool(external.get("repository") and external.get("branch") and external.get("pull_request"))
        if not valid:
            task["status"] = "NOW"
        return valid

    try:
        result = continue_verified(state, execute_step, verify_step, max_attempts=max_attempts)
    except ContinuationHalt as exc:
        raise RuntimeError(str(exc)) from exc
    return verify_task(result.result, workspace)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", default="BAŞLA")
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--task")
    parser.add_argument("--authority-log", default=AUTHORITY_LOG)
    parser.add_argument("--max-attempts", type=int, default=3)
    args = parser.parse_args()
    workspace = Path(args.workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    os.chdir(workspace)
    validate_workspace()
    state = load_state()
    command = args.command.upper()
    if command == "BAŞLA":
        state = initialize_state(state, ".")
    elif command == "RECONCILE":
        state = initialize_state(state, ".")
        state = reconcile_discovered_tasks(state)
        state["status"] = "RECONCILED"
        state["step"] = 1
    elif command == "REQUEST_APPROVAL":
        if not args.task:
            raise RuntimeError("HALT: --task is required.")
        state = initialize_state(state, ".")
        state = reconcile_discovered_tasks(state)
        state = request_approval(state, args.task)
    elif command == "APPROVE":
        if not args.task:
            raise RuntimeError("HALT: --task is required.")
        state = initialize_state(state, ".")
        state = reconcile_discovered_tasks(state)
        state = approve_task(state, args.task)
    elif command == "EXECUTE":
        state = execute_task(state, ".")
    elif command == "VERIFY":
        state = verify_task(state, ".")
    elif command == "CONTINUE":
        if not args.task:
            raise RuntimeError("HALT: --task is required for CONTINUE.")
        state = initialize_state(state, ".")
        state = request_approval(state, args.task)
        state = approve_task(state, args.task)
        state = continue_execution(state, ".", max_attempts=args.max_attempts)
    elif command == "RUN":
        raise RuntimeError("HALT: RUN cannot autonomously approve a task. Use canonical Authority Gate approval before EXECUTE.")
    else:
        raise RuntimeError(f"HALT: Unknown command: {args.command}")
    state["last_updated"] = utc_now()
    print(json.dumps(state, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

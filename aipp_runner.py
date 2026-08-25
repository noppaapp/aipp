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

import argparse
import base64
import json
import os
import sys
import hashlib
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from aipp_project_bootstrap import bootstrap_project_from_text
from aipp_authority import AUTHORITY_LOG, AUTHORITY_ENV, binding_digest, is_approved, is_completion_approved, proposal_id
from aipp_drive_runtime import reconcile_discovered_tasks
from runtime.continuation import ContinuationHalt, continue_verified
from runtime.github_external import ExternalActionHalt, execute_bounded_github_proof
from runtime.github_target import TargetProjectHalt, apply_text_file

AIPP_SPEC = "AIPP.md"
ARTIFACT_DIR = Path("artifacts")
DISCOVERED_TASKS_ENV = "AIPP_DISCOVERED_TASKS_B64"
PROJECT_INTELLIGENCE_ENV = "AIPP_PROJECT_INTELLIGENCE_B64"
COMPLETION_GATE_ENV = "AIPP_REQUIRE_COMPLETION_GATE"


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
    # The Drive-supplied canonical PROJECT_BOOT.md wins. The repo's own copy is
    # only a fallback for local/dev runs.
    encoded = os.environ.get("AIPP_PROJECT_BOOT_B64", "").strip()
    if encoded:
        try:
            return base64.b64decode(encoded).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise RuntimeError("HALT: Canonical PROJECT_BOOT.md transport is invalid") from exc
    boot_path = Path(workspace) / "PROJECT_BOOT.md"
    if boot_path.exists():
        return boot_path.read_text(encoding="utf-8")
    raise RuntimeError("HALT: Canonical PROJECT_BOOT.md was not supplied by Drive runtime")


def load_canonical_authority_log():
    encoded = os.environ.get(AUTHORITY_ENV, "").strip()
    if not encoded:
        return ""
    try:
        return base64.b64decode(encoded).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise RuntimeError("HALT: Canonical AUTHORITY_LOG.md transport is invalid") from exc


def load_discovered_tasks():
    encoded = os.environ.get(DISCOVERED_TASKS_ENV, "").strip()
    if not encoded:
        return []
    try:
        value = json.loads(base64.b64decode(encoded).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("HALT: Discovered Drive task transport is invalid") from exc
    if not isinstance(value, list):
        raise RuntimeError("HALT: Discovered Drive task transport must be a list")
    return value


def load_project_intelligence():
    encoded = os.environ.get(PROJECT_INTELLIGENCE_ENV, "").strip()
    if not encoded:
        return {"version": "0", "findings": [], "proposals": []}
    try:
        value = json.loads(base64.b64decode(encoded).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("HALT: Project intelligence transport is invalid") from exc
    if not isinstance(value, dict):
        raise RuntimeError("HALT: Project intelligence transport must be an object")
    return value


def build_workspace_map(project_boot_text, discovered_tasks, intelligence):
    """Create a compact evidence-backed workspace model without another scan."""
    evidence = intelligence.get("evidence") or []
    areas = {}
    for item in evidence:
        kind = item.get("kind") or "reference"
        areas.setdefault(kind, [])
        if item.get("file_name") not in areas[kind]:
            areas[kind].append(item.get("file_name"))
    open_tasks = []
    for item in discovered_tasks or []:
        for task_id in item.get("task_ids", []):
            open_tasks.append({"id": task_id, "source": item.get("name")})
    proposals = intelligence.get("proposals") or []
    findings = intelligence.get("findings") or []
    recent = sorted(
        [{"name": x.get("file_name"), "modifiedTime": x.get("modifiedTime"), "kind": x.get("kind")}
         for x in evidence if x.get("modifiedTime")],
        key=lambda x: str(x.get("modifiedTime")), reverse=True,
    )[:10]
    canonical = [
        {"name": x.get("file_name"), "kind": x.get("kind"), "modifiedTime": x.get("modifiedTime")}
        for x in evidence if x.get("file_name") in {"PROJECT_BOOT.md", "AIPP.md"}
    ]
    return {
        "version": "1",
        "status": "OPEN_WORK_REMAINING" if open_tasks or proposals else ("SIGNALS_FOUND" if findings else "EMPTY"),
        "purpose_evidence": " ".join(str(project_boot_text or "").split())[:700],
        "document_count": len(evidence),
        "areas": [{"area": k, "document_count": len(v), "sources": v[:8]} for k, v in sorted(areas.items())],
        "canonical_sources": canonical,
        "open_tasks": open_tasks,
        "finding_count": len(findings),
        "proposal_count": len(proposals),
        "recent_changes": recent,
    }


def reconcile_project_intelligence(state, intelligence):
    result = state
    lifecycle = result.setdefault("task_lifecycle", {})
    future = lifecycle.setdefault("FUTURE", [])
    priority_rank = {"status_conflict":100,"task_definition_drift":95,"newer_supporting_source":85,"actionable_untracked_idea":70,"near_duplicate":60,"workspace_review_required":10}
    existing_ids = {
        task.get("id")
        for bucket in ("NOW", "DEFERRED", "BLOCKED", "FUTURE", "REFERENCE", "COMPLETED")
        for task in ([lifecycle.get(bucket)] if bucket == "NOW" else (lifecycle.get(bucket) or []))
        if isinstance(task, dict) and task.get("id")
    }
    # Replace the old generic fallback proposal with the current evidence-backed
    # proposal set. A fresh Drive scan must not keep surfacing stale INTEL-0001.
    future[:] = [
        task for task in future
        if not (
            str(task.get("id", "")).startswith("INTEL-")
            and task.get("source", {}).get("finding_type") == "workspace_review_required"
        )
    ]
    existing_ids = {
        task.get("id")
        for bucket in ("NOW", "DEFERRED", "BLOCKED", "FUTURE", "REFERENCE", "COMPLETED")
        for task in ([lifecycle.get(bucket)] if bucket == "NOW" else (lifecycle.get(bucket) or []))
        if isinstance(task, dict) and task.get("id")
    }
    for proposal in intelligence.get("proposals", []):
        fingerprint = json.dumps({
            "action": proposal.get("action"),
            "target": proposal.get("target"),
            "finding_type": proposal.get("finding_type"),
        }, ensure_ascii=False, sort_keys=True)
        proposal_id_value = "INTEL-" + hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:10].upper()
        if proposal_id_value in existing_ids:
            continue
        future.append({
            "id": proposal_id_value,
            "title": f"İncele: {proposal.get('target')}",
            "description": proposal.get("reason"),
            "status": "PROPOSED",
            "proposal_reason": proposal.get("reason"),
            "recommendation": proposal.get("recommendation", proposal.get("reason", "")),
            "source": {
                "engine": intelligence.get("engine"),
                "finding_type": proposal.get("finding_type"),
                "target": proposal.get("target"),
                "evidence": proposal.get("evidence", []),
            },
            "change_action": proposal.get("action"),
            "next_action": proposal.get("next_action", ""),
            "requires_authority": True,
            "priority": int(proposal.get("priority", priority_rank.get(proposal.get("finding_type"), 50))),
        })
        existing_ids.add(proposal_id_value)
    future.sort(key=lambda item: (-int(item.get("priority", 50)), str(item.get("id", ""))))
    result["intelligence_queue"] = [item.get("id") for item in future if item.get("id")]
    result["project_intelligence"] = {
        "version": intelligence.get("version"), "engine": intelligence.get("engine"),
        "documents_scanned": intelligence.get("documents_scanned", 0),
        "finding_count": len(intelligence.get("findings", [])),
        "proposal_count": len(intelligence.get("proposals", [])),
        "queue_count": len(future),
        "queue": [{"id":x.get("id"),"title":x.get("title"),"priority":x.get("priority",50),"finding_type":x.get("source",{}).get("finding_type")} for x in future],
    }
    if intelligence.get("proposals"):
        result.setdefault("authority_gate", {})["last_action"] = "PROJECT_INTELLIGENCE_PROPOSALS"
    return result


def default_state():
    return {
        "version": "1.1.1",
        "status": "INITIALIZED",
        "active_project": None,
        "execution_mode": "REAL",
        "task_lifecycle": {"NOW": None, "DEFERRED": [], "BLOCKED": [], "FUTURE": [], "REFERENCE": [], "COMPLETED": []},
        "authority_gate": {"pending_approval": None, "last_action": "INITIALIZATION"},
        "step": 0,
        "runner_engine": os.environ.get("AIPP_RUNTIME_ENGINE", "AIPP Standalone Cloud Runtime"),
    }


def load_state():
    encoded = os.environ.get("AIPP_SESSION_STATE_B64", "").strip()
    if encoded:
        try:
            value = json.loads(base64.b64decode(encoded).decode("utf-8"))
            if isinstance(value, dict):
                return value
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("HALT: Persisted session state transport is invalid") from exc
    return default_state()


def recommend_next_proposal(state, workspace):
    """Create a deterministic passive proposal from a concrete workspace signal."""
    lifecycle = state.get("task_lifecycle", {})
    if lifecycle.get("NOW") or lifecycle.get("FUTURE"):
        return state

    proof_path = Path(workspace) / "AIPP_EXECUTION_PROOF.md"
    if not proof_path.exists():
        return state
    proof_text = proof_path.read_text(encoding="utf-8")
    if "Status: PROOF_REQUESTED" not in proof_text:
        return state

    task_ids = []
    for bucket in ("DEFERRED", "BLOCKED", "FUTURE", "REFERENCE", "COMPLETED"):
        for task in lifecycle.get(bucket) or []:
            if isinstance(task, dict) and task.get("id"):
                task_ids.append(str(task["id"]))
    import re
    numeric_ids = [
        int(match.group(1))
        for task_id in task_ids
        if (match := re.fullmatch(r"TASK-(\d+)", task_id))
    ]
    next_number = max(numeric_ids, default=0) + 1
    proposal = {
        "id": f"TASK-{next_number:02d}",
        "title": "AIPP yürütme kanıtını tamamla",
        "description": "Bekleyen gerçek yürütme kanıtını tamamla ve yapılandırılmış dış yürütme yeteneğini doğrula.",
        "status": "PROPOSED",
        "proposal_reason": "AIPP_EXECUTION_PROOF.md belgesi PROOF_REQUESTED olarak işaretli, ancak bekleyen TASK bulunmuyor.",
        "capability": "external_execution_proof",
        "source": {"artifact": "AIPP_EXECUTION_PROOF.md", "signal": "PROOF_REQUESTED"},
    }
    lifecycle.setdefault("FUTURE", []).append(proposal)
    state.setdefault("authority_gate", {})["pending_approval"] = None
    state["authority_gate"]["last_action"] = "AUTONOMOUS_PROPOSAL_CREATED"
    state["status"] = "PROPOSAL_READY"
    return state


def initialize_state(state, workspace):
    boot_text = load_canonical_project_boot(workspace)
    discovered_tasks = load_discovered_tasks()
    state = bootstrap_project_from_text(boot_text, state)
    state = reconcile_discovered_tasks(state, discovered_tasks)
    intelligence = load_project_intelligence()
    state = reconcile_project_intelligence(state, intelligence)
    state["workspace_map"] = build_workspace_map(boot_text, discovered_tasks, intelligence)
    lifecycle = state.setdefault("task_lifecycle", {})
    # A concrete passive proof signal must win over the generic workspace-review fallback.
    state = recommend_next_proposal(state, workspace)
    # If the current scan produced evidence-backed proposals, never manufacture
    # the old generic "workspace review" task. Only use the generic fallback when
    # the workspace truly contains no actionable signal at all.
    if not lifecycle.get("NOW") and not lifecycle.get("FUTURE") and not intelligence.get("proposals"):
        lifecycle.setdefault("FUTURE", []).append({
            "id": "INTEL-WORKSPACE-REVIEW",
            "title": "AIPP çalışma alanını incele",
            "description": "Açık bir TASK veya doğrulanabilir öneri bulunamadı.",
            "status": "PROPOSED",
            "proposal_reason": "Çalışma alanında açık bir TASK bulunamadı ve yeni bir kanıta dayalı öneri üretilemedi.",
            "recommendation": "Yeni bir somut aksiyon oluşana kadar bekle.",
            "source": {"engine": intelligence.get("engine", "deterministic-workspace-fallback"), "finding_type": "workspace_review_required", "evidence": []},
            "change_action": "REVIEW",
            "next_action": "Yeni bir kanıt veya TASK oluşmasını beklemek.",
            "requires_authority": True,
        })
    if state["task_lifecycle"].get("FUTURE"):
        state["status"] = "PROPOSAL_READY"
        state["step"] = 1
    else:
        # A scan with no unresolved queue is a real terminal state. Do not
        # advertise PROPOSAL_READY with an empty proposal.
        state["status"] = "COMPLETED"
        state["step"] = 4
        state.setdefault("authority_gate", {})["last_action"] = "SCAN_COMPLETE_NO_UNRESOLVED_FINDINGS"
    return state


def find_future_task(state, task_id):
    return next((task for task in state["task_lifecycle"].get("FUTURE", []) if task.get("id") == task_id), None)


def request_approval(state, task_id):
    task = find_future_task(state, task_id)
    if task is None:
        current = [
            item.get("id")
            for item in state["task_lifecycle"].get("FUTURE", [])
            if isinstance(item, dict) and item.get("id")
        ]
        raise RuntimeError(
            f"HALT: FUTURE task not found: {task_id} (current FUTURE ids: {current}). Re-run BAŞLA."
        )
    state["authority_gate"]["pending_approval"] = task_id
    state["authority_gate"]["pending_proposal_id"] = proposal_id(task)
    state["authority_gate"]["last_action"] = "APPROVAL_REQUESTED"
    state["status"] = "AWAITING_AUTHORITY"
    return state


def approve_task(state, task_id, authority_log=None):
    pending = state["authority_gate"].get("pending_approval")
    if pending != task_id:
        raise RuntimeError(f"HALT: Authority Gate mismatch. pending={pending}, requested={task_id}")
    task = find_future_task(state, task_id)
    if task is None:
        raise RuntimeError(f"HALT: Task disappeared from FUTURE: {task_id}")
    expected_proposal = state["authority_gate"].get("pending_proposal_id")
    actual_proposal = proposal_id(task)
    if expected_proposal != actual_proposal:
        raise RuntimeError("HALT: Proposal changed after approval request")
    source = load_canonical_authority_log() if authority_log is None else authority_log
    if not is_approved(source, task):
        raise RuntimeError(f"HALT: Canonical Authority Gate approval not found: {actual_proposal}")
    state["task_lifecycle"]["FUTURE"].remove(task)
    task["status"] = "APPROVED"
    task["proposal_id"] = actual_proposal
    task["binding_digest"] = binding_digest(task)
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
    if task.get("binding_digest") != binding_digest(task) and (
        task.get("binding_digest") is not None or task.get("status") == "APPROVED"
    ):
        raise RuntimeError("HALT: Task payload changed after approval (binding digest mismatch)")
    external_result = None
    try:
        if task.get("external_action") == "GITHUB_PROOF_BRANCH":
            external_result = execute_bounded_github_proof(task["id"])
        elif task.get("external_action") == "GITHUB_TARGET_TEXT_FILE":
            external_result = apply_text_file(task["id"], task.get("target_path", ""), task.get("target_content", ""), title=task.get("title"), body=task.get("description"))
    except (ExternalActionHalt, TargetProjectHalt) as exc:
        raise RuntimeError(str(exc)) from exc
    artifact_dir = Path(workspace) / ARTIFACT_DIR
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / f"{task['id']}-execution.json"
    intelligence = load_project_intelligence()
    review_result = None
    if task.get("source", {}).get("finding_type") == "workspace_review_required":
        review_result = {
            "type": "workspace_review",
            "documents_scanned": intelligence.get("documents_scanned", 0),
            "findings": intelligence.get("findings", []),
            "proposals": intelligence.get("proposals", []),
            "completed_action": "Bütünsel çalışma alanı incelemesi oluşturuldu ve doğrulama için kaydedildi.",
        }
    save_json(artifact_path, {"task_id": task["id"], "title": task.get("title"), "execution_mode": state.get("execution_mode", "REAL"), "executed_at": utc_now(), "runner": state.get("runner_engine"), "external_result": external_result, "review_result": review_result, "result": "EXECUTED"})
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
    if task.get("binding_digest") is not None and task["binding_digest"] != binding_digest(task):
        raise RuntimeError("HALT: Task payload changed after approval (binding digest mismatch)")
    task["verified_at"] = utc_now()
    if os.environ.get(COMPLETION_GATE_ENV, "").strip() == "1":
        task["status"] = "VERIFIED"
        state["authority_gate"]["pending_completion"] = task["id"]
        state["authority_gate"]["last_action"] = "VERIFICATION_PASSED_AWAITING_COMPLETION_AUTHORITY"
        state["status"] = "AWAITING_COMPLETION_AUTHORITY"
        state["step"] = 3
        return state
    return _finalize_completion(state, task)


def _finalize_completion(state, task):
    task["status"] = "COMPLETED"
    task.setdefault("verified_at", utc_now())
    state["task_lifecycle"]["COMPLETED"].append(task)
    state["task_lifecycle"]["NOW"] = None
    state.setdefault("authority_gate", {})["pending_completion"] = None

    # Verification is not the end of an AIPP session. Reconcile the fresh
    # workspace intelligence immediately so a completed proposal cannot block
    # the next actionable proposal. Existing COMPLETED/FUTURE ids are preserved
    # and only genuinely new proposals are surfaced.
    intelligence = load_project_intelligence()
    state = reconcile_project_intelligence(state, intelligence)

    if state["task_lifecycle"].get("FUTURE"):
        state["status"] = "PROPOSAL_READY"
        state["step"] = 1
        state["authority_gate"]["last_action"] = "VERIFIED_NEXT_PROPOSAL_READY"
    else:
        state["status"] = "COMPLETED"
        state["step"] = 4
        state["authority_gate"]["last_action"] = "VERIFIED"

    return state


def complete_task(state, task_id, authority_log=None):
    """Authority-gated VERIFIED -> COMPLETED transition."""
    task = state["task_lifecycle"].get("NOW")
    if not task or task.get("id") != task_id or task.get("status") != "VERIFIED":
        raise RuntimeError(f"HALT: No VERIFIED task awaiting completion authority: {task_id}")
    if task.get("binding_digest") is not None and task["binding_digest"] != binding_digest(task):
        raise RuntimeError("HALT: Task payload changed after approval (binding digest mismatch)")
    source = load_canonical_authority_log() if authority_log is None else authority_log
    if not is_completion_approved(source, task):
        raise RuntimeError(f"HALT: Canonical completion approval not found: {task.get('proposal_id')}")
    return _finalize_completion(state, task)


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
    elif command == "REQUEST_APPROVAL":
        if not args.task:
            raise RuntimeError("HALT: --task is required.")
        state = request_approval(state, args.task)
    elif command == "APPROVE":
        if not args.task:
            raise RuntimeError("HALT: --task is required.")
        state = request_approval(state, args.task)
        state = approve_task(state, args.task)
    elif command == "EXECUTE":
        state = execute_task(state, ".")
    elif command == "EXECUTE_APPROVED":
        if not args.task:
            raise RuntimeError("HALT: --task is required.")
        state = request_approval(state, args.task)
        state = approve_task(state, args.task)
        state = execute_task(state, ".")
    elif command == "VERIFY":
        state = verify_task(state, ".")
    elif command == "COMPLETE":
        if not args.task:
            raise RuntimeError("HALT: --task is required for COMPLETE.")
        state = complete_task(state, args.task)
    elif command == "CONTINUE":
        if not args.task:
            raise RuntimeError("HALT: --task is required for CONTINUE.")
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

import re
from pathlib import Path

LIFECYCLE_STATUSES = {"NOW", "DEFERRED", "BLOCKED", "FUTURE", "REFERENCE", "COMPLETED"}


def _clean_cell(value):
    value = value.strip()
    value = re.sub(r"^\*\*|\*\*$", "", value).strip()
    value = re.sub(r"^`|`$", "", value).strip()
    return value


def parse_project_boot_text(text):
    project = None
    status = None
    active_state = None
    tasks = []
    for line in text.splitlines():
        if line.startswith("# PROJECT_BOOT:"):
            project = line.split(":", 1)[1].strip()
        elif "**Workspace Status:**" in line:
            status = line.split("**Workspace Status:**", 1)[1].strip()
        elif "**Active State:**" in line:
            active_state = line.split("**Active State:**", 1)[1].strip()
        if line.lstrip().startswith("|"):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) >= 4:
                task_id = _clean_cell(cells[0])
                title = _clean_cell(cells[1])
                task_status = _clean_cell(cells[2]).upper()
                dependency = _clean_cell(cells[3])
                # Task IDs are workspace-defined identifiers. AIPP must not
                # invent a TASK- prefix requirement that the canonical workspace
                # did not define.
                if task_id and task_id.lower() not in {"task id", ":---"} and task_status in LIFECYCLE_STATUSES:
                    tasks.append({"id": task_id, "title": title, "status": task_status, "dependency_reason": dependency})
    return {"project": project, "workspace_status": status, "active_state": active_state, "tasks": tasks}


def parse_project_boot(path):
    return parse_project_boot_text(Path(path).read_text(encoding="utf-8"))


def bootstrap_project_from_text(text, state):
    boot = parse_project_boot_text(text)
    state["active_project"] = boot["project"]
    state["project_bootstrap"] = {
        "workspace_status": boot["workspace_status"],
        "active_state": boot["active_state"],
        "source": "PROJECT_BOOT.md",
    }
    lifecycle = state.setdefault("task_lifecycle", {})
    for status in LIFECYCLE_STATUSES:
        value = lifecycle.get(status)
        lifecycle[status] = value if status == "NOW" else (value if isinstance(value, list) else [])
    existing = {status: ({task.get("id") for task in lifecycle[status]} if status != "NOW" else set()) for status in LIFECYCLE_STATUSES}
    for task in boot["tasks"]:
        task_id, status = task["id"], task["status"]
        if status == "NOW":
            if lifecycle["NOW"] is None and task_id not in existing["COMPLETED"]:
                lifecycle["NOW"] = task
            continue
        if task_id in existing[status]:
            continue
        for other_status in LIFECYCLE_STATUSES - {status, "NOW"}:
            lifecycle[other_status] = [item for item in lifecycle[other_status] if item.get("id") != task_id]
            existing[other_status].discard(task_id)
        lifecycle[status].append(task)
        existing[status].add(task_id)
    state["status"] = "PROPOSAL_READY"
    state["step"] = max(state.get("step", 0), 1)
    state.setdefault("authority_gate", {})["last_action"] = "PROJECT_BOOTSTRAPPED"
    return state


def bootstrap_project(workspace, state):
    return bootstrap_project_from_text((Path(workspace) / "PROJECT_BOOT.md").read_text(encoding="utf-8"), state)

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
    # NOW is semantically a single slot; the other lifecycle buckets are lists.
    if not isinstance(lifecycle.get("NOW"), (dict, type(None))):
        lifecycle["NOW"] = None
    for status in LIFECYCLE_STATUSES - {"NOW"}:
        value = lifecycle.get(status)
        lifecycle[status] = value if isinstance(value, list) else []
    existing = {status: {task.get("id") for task in lifecycle[status]} for status in LIFECYCLE_STATUSES - {"NOW"}}
    # PROJECT_BOOT is the canonical source for bootstrap mapping. Do not
    # merge unrelated discovery candidates into its lifecycle state.
    for task in boot["tasks"]:
        task_id, status = task["id"], task["status"]
        for other_status in LIFECYCLE_STATUSES - {"NOW", status}:
            lifecycle[other_status] = [item for item in lifecycle[other_status] if item.get("id") != task_id]
            existing[other_status].discard(task_id)
        if status == "NOW":
            lifecycle["NOW"] = task
        elif task_id not in existing[status]:
            lifecycle[status].append(task)
            existing[status].add(task_id)
    state["status"] = "PROPOSAL_READY"
    state["step"] = max(state.get("step", 0), 1)
    state.setdefault("authority_gate", {})["last_action"] = "PROJECT_BOOTSTRAPPED"
    return state


def bootstrap_project(workspace, state):
    return bootstrap_project_from_text((Path(workspace) / "PROJECT_BOOT.md").read_text(encoding="utf-8"), state)

import re
from pathlib import Path


LIFECYCLE_STATUSES = {"NOW", "DEFERRED", "BLOCKED", "FUTURE", "REFERENCE", "COMPLETED"}


def _clean_cell(value):
    value = value.strip()
    value = re.sub(r"^\*\*|\*\*$", "", value).strip()
    value = re.sub(r"^`|`$", "", value).strip()
    return value


def parse_project_boot(path):
    text = Path(path).read_text(encoding="utf-8")
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

        # Parse canonical Markdown task rows by cells rather than relying on
        # formatting details such as backticks around individual cells.
        if line.lstrip().startswith("|"):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) >= 4:
                task_id = _clean_cell(cells[0])
                title = _clean_cell(cells[1])
                task_status = _clean_cell(cells[2]).upper()
                dependency = _clean_cell(cells[3])
                if task_id.startswith("TASK-") and task_status in LIFECYCLE_STATUSES:
                    tasks.append({
                        "id": task_id,
                        "title": title,
                        "status": task_status,
                        "dependency_reason": dependency,
                    })

    return {
        "project": project,
        "workspace_status": status,
        "active_state": active_state,
        "tasks": tasks,
    }


def bootstrap_project(workspace, state):
    boot_path = Path(workspace) / "PROJECT_BOOT.md"
    boot = parse_project_boot(boot_path)

    state["active_project"] = boot["project"]
    state["project_bootstrap"] = {
        "workspace_status": boot["workspace_status"],
        "active_state": boot["active_state"],
        "source": "PROJECT_BOOT.md",
    }

    lifecycle = state["task_lifecycle"]
    for status in LIFECYCLE_STATUSES:
        lifecycle.setdefault(status, [])

    existing = {
        status: {task.get("id") for task in lifecycle.get(status, [])}
        for status in LIFECYCLE_STATUSES
    }

    for task in boot["tasks"]:
        task_id = task["id"]
        status = task["status"]

        # Canonical PROJECT_BOOT is authoritative for bootstrap mapping.
        # Never move a task to NOW automatically. NOW remains authority-gated.
        if status == "NOW":
            if lifecycle.get("NOW") is None and task_id not in existing["COMPLETED"]:
                lifecycle["NOW"] = task
            continue

        if task_id in existing[status]:
            continue

        for other_status in LIFECYCLE_STATUSES - {status, "NOW"}:
            lifecycle[other_status] = [
                item for item in lifecycle.get(other_status, [])
                if item.get("id") != task_id
            ]

        lifecycle[status].append(task)
        existing[status].add(task_id)

    state["status"] = "PROJECT_READY"
    state["step"] = max(state.get("step", 0), 1)
    state["authority_gate"]["last_action"] = "PROJECT_BOOTSTRAPPED"
    return state

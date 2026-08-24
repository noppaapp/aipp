import re
from pathlib import Path


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

        match = re.match(r"\|\s*\*\*(TASK-[^*]+)\*\*\s*\|\s*`?([^|]+?)`?\s*\|\s*`?(COMPLETED|NOW|DEFERRED|BLOCKED|FUTURE|REFERENCE)`?\s*\|\s*([^|]+?)\s*\|", line)
        if match:
            tasks.append({
                "id": match.group(1).strip(),
                "title": match.group(2).strip(),
                "status": match.group(3).strip(),
                "dependency_reason": match.group(4).strip()
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
    completed = {task.get("id") for task in lifecycle.get("COMPLETED", [])}
    future = {task.get("id") for task in lifecycle.get("FUTURE", [])}

    for task in boot["tasks"]:
        if task["status"] == "COMPLETED" and task["id"] not in completed:
            lifecycle["COMPLETED"].append(task)
        elif task["status"] in {"FUTURE", "DEFERRED", "BLOCKED", "REFERENCE"} and task["id"] not in future:
            lifecycle[task["status"]].append(task)

    state["status"] = "PROJECT_READY"
    state["step"] = max(state.get("step", 0), 1)
    state["authority_gate"]["last_action"] = "PROJECT_BOOTSTRAPPED"
    return state

from aipp_drive_runtime import reconcile_discovered_tasks


def test_discovered_tasks_become_future_without_crossing_authority_gate():
    state = {
        "status": "PROPOSAL_READY",
        "task_lifecycle": {
            "NOW": None,
            "DEFERRED": [],
            "BLOCKED": [],
            "FUTURE": [],
            "REFERENCE": [],
            "COMPLETED": [],
        },
        "authority_gate": {
            "pending_approval": None,
            "last_action": "INITIALIZATION",
        },
    }
    candidates = [
        {
            "id": "file-1",
            "name": "AIPP Tasks.md",
            "mimeType": "text/markdown",
            "task_ids": ["TASK-05"],
            "parents": ["workspace"],
        }
    ]

    result = reconcile_discovered_tasks(state, candidates)

    assert result["task_lifecycle"]["NOW"] is None
    assert [task["id"] for task in result["task_lifecycle"]["FUTURE"]] == ["TASK-05"]
    assert result["task_lifecycle"]["FUTURE"][0]["status"] == "PROPOSED"
    assert result["authority_gate"]["pending_approval"] is None
    assert result["authority_gate"]["last_action"] == "WORKSPACE_DISCOVERY_PROPOSALS"


def test_reconciliation_does_not_duplicate_existing_tasks():
    state = {
        "status": "PROPOSAL_READY",
        "task_lifecycle": {
            "NOW": None,
            "DEFERRED": [],
            "BLOCKED": [],
            "FUTURE": [{"id": "TASK-05", "status": "PROPOSED"}],
            "REFERENCE": [],
            "COMPLETED": [],
        },
        "authority_gate": {
            "pending_approval": None,
            "last_action": "INITIALIZATION",
        },
    }

    result = reconcile_discovered_tasks(
        state,
        [{"id": "file-1", "name": "tasks.md", "mimeType": "text/markdown", "task_ids": ["TASK-05"]}],
    )

    assert [task["id"] for task in result["task_lifecycle"]["FUTURE"]] == ["TASK-05"]

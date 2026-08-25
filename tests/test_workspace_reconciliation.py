from aipp_drive_runtime import reconcile_discovered_tasks


def test_discovered_tasks_stay_in_candidate_pool_without_crossing_canonical_lifecycle():
    state = {
        "status": "PROPOSAL_READY",
        "task_lifecycle": {
            "NOW": None,
            "DEFERRED": [],
            "BLOCKED": [],
            "FUTURE": [{"id": "TASK-02", "status": "FUTURE"}],
            "REFERENCE": [],
            "COMPLETED": [{"id": "TASK-01", "status": "COMPLETED"}],
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
            "task_ids": ["TASK-01", "TASK-02", "TASK-03", "TASK-04"],
            "parents": ["workspace"],
        }
    ]

    result = reconcile_discovered_tasks(state, candidates)

    assert [task["id"] for task in result["task_lifecycle"]["FUTURE"]] == ["TASK-02"]
    assert [task["id"] for task in result["task_lifecycle"]["COMPLETED"]] == ["TASK-01"]
    assert [candidate["task_ids"] for candidate in result["discovered_candidates"]] == [["TASK-01", "TASK-02", "TASK-03", "TASK-04"]]
    assert result["authority_gate"]["pending_approval"] is None
    assert result["authority_gate"]["last_action"] == "WORKSPACE_DISCOVERY_CANDIDATES"


def test_reconciliation_does_not_mutate_canonical_lifecycle():
    state = {
        "status": "PROPOSAL_READY",
        "task_lifecycle": {
            "NOW": None,
            "DEFERRED": [],
            "BLOCKED": [],
            "FUTURE": [{"id": "TASK-05", "status": "FUTURE"}],
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
        [{"id": "file-1", "name": "tasks.md", "mimeType": "text/markdown", "task_ids": ["TASK-05", "TASK-06"]}],
    )

    assert [task["id"] for task in result["task_lifecycle"]["FUTURE"]] == ["TASK-05"]
    assert [candidate["task_ids"] for candidate in result["discovered_candidates"]] == [["TASK-05", "TASK-06"]]

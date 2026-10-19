import pytest

from aipp_runner import execute_task


@pytest.mark.parametrize(
    ("task", "expected_message"),
    [
        (
            {
                "id": "INTEL-REVIEW-01",
                "title": "Review PROJECT_BOOT.md",
                "status": "NOW",
                "source": {"finding_type": "workspace_review_required"},
            },
            "İnceleme ve öneri görevleri yürütülemez",
        ),
        (
            {
                "id": "TASK-UNSUPPORTED-01",
                "title": "Unsupported generic task",
                "status": "NOW",
                "source": {"finding_type": "actionable_untracked_idea"},
            },
            "İnceleme ve öneri görevleri yürütülemez",
        ),
        (
            {
                "id": "TASK-UNKNOWN-ACTION-01",
                "title": "Unknown action",
                "status": "NOW",
                "external_action": "UNSUPPORTED_ACTION",
                "source": {"finding_type": "implementation_task"},
            },
            "Desteklenmeyen işlem türü",
        ),
    ],
)
def test_unsupported_or_review_only_tasks_fail_closed(tmp_path, task, expected_message):
    state = {
        "status": "NOW",
        "step": 2,
        "execution_mode": "REAL",
        "task_lifecycle": {"NOW": task, "FUTURE": [], "COMPLETED": []},
        "authority_gate": {},
    }

    with pytest.raises(RuntimeError, match=expected_message):
        execute_task(state, tmp_path)

    assert not (tmp_path / "artifacts").exists()
    assert task["status"] == "NOW"

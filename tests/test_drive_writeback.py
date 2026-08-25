import pytest

from aipp_drive_writeback import WriteBackError, mutate_project_boot_task_status


BOOT = """# PROJECT_BOOT: Demo Project

**Workspace Status:** ACTIVE
**Active State:** [READY]

| Task ID | Task Description | Status | Dependency / Reason |
| :--- | :--- | :--- | :--- |
| **TASK-01** | `First task` | `NOW` | - |
| **TASK-02** | `Second task` | `FUTURE` | TASK-01 |
"""


def test_completion_mutates_only_canonical_task():
    updated = mutate_project_boot_task_status(BOOT, "TASK-01")
    assert "| **TASK-01** | `First task` | COMPLETED | - |" in updated
    assert "| **TASK-02** | `Second task` | `FUTURE` | TASK-01 |" in updated


def test_completion_requires_exactly_one_canonical_task():
    with pytest.raises(WriteBackError):
        mutate_project_boot_task_status(BOOT, "TASK-99")


def test_completion_is_idempotent():
    completed = mutate_project_boot_task_status(BOOT, "TASK-01")
    assert mutate_project_boot_task_status(completed, "TASK-01") == completed


def test_completion_rejects_unsupported_status():
    with pytest.raises(WriteBackError):
        mutate_project_boot_task_status(BOOT, "TASK-01", "FUTURE")

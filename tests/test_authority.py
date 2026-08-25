from aipp_authority import is_approved, proposal_id


def task():
    return {
        "id": "TASK-01",
        "title": "Execution proof",
        "status": "FUTURE",
        "dependency_reason": "-",
    }


def authority_text(pid):
    return (
        "# AUTHORITY_LOG\n\n"
        "| Proposal ID | Task ID | Decision | Timestamp | Note |\n"
        "| :--- | :--- | :--- | :--- | :--- |\n"
        f"| {pid} | TASK-01 | APPROVED | 2026-08-25T00:00:00Z | human |\n"
    )


def test_proposal_id_is_deterministic():
    assert proposal_id(task()) == proposal_id(task())


def test_proposal_id_changes_when_proposal_changes():
    changed = task()
    changed["title"] = "Changed proposal"
    assert proposal_id(task()) != proposal_id(changed)


def test_authority_requires_exact_task_and_proposal(tmp_path):
    current = task()
    pid = proposal_id(current)
    log = tmp_path / "AUTHORITY_LOG.md"
    log.write_text(authority_text(pid), encoding="utf-8")
    assert is_approved(log, current)


def test_authority_can_be_verified_from_canonical_drive_text():
    current = task()
    pid = proposal_id(current)
    assert is_approved(authority_text(pid), current)


def test_old_approval_does_not_authorize_changed_proposal(tmp_path):
    current = task()
    pid = proposal_id(current)
    changed = task()
    changed["dependency_reason"] = "TASK-00"
    log = tmp_path / "AUTHORITY_LOG.md"
    log.write_text(authority_text(pid), encoding="utf-8")
    assert not is_approved(log, changed)

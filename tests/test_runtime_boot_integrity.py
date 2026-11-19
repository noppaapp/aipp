def test_drive_context_surfaces_incomplete_canonical_boot_for_review(monkeypatch):
    import runtime_service

    boot_text = "# AIPP RUNTIME BOOT\n\nAIPP v1.0 runtime workspace.\n"
    monkeypatch.setenv("GDRIVE_FOLDER_ID", "aipp-root")
    monkeypatch.delenv("NOPPA_GDRIVE_FOLDER_ID", raising=False)
    monkeypatch.setattr(runtime_service, "get_access_token", lambda: "access")
    monkeypatch.setattr(runtime_service, "find_project_boot", lambda *_: {"id": "boot-id"})
    monkeypatch.setattr(
        runtime_service,
        "read_file_text",
        lambda _token, info: boot_text if info["id"] == "boot-id" else "",
    )
    monkeypatch.setattr(runtime_service, "find_authority_log", lambda *_: None)
    monkeypatch.setattr(
        runtime_service,
        "discover_task_candidates",
        lambda *_args, **kwargs: (
            [], [], {
                "files_scanned": 1,
                "documents_read": 1,
                "documents_unreadable": 0,
                "folders_scanned": 0,
                "task_candidates": 0,
            }
        ),
    )
    monkeypatch.setattr(
        runtime_service,
        "analyze_documents",
        lambda _documents: {
            "version": "2",
            "findings": [],
            "proposals": [],
            "evidence": [],
        },
    )
    monkeypatch.setattr(
        runtime_service,
        "analyze_with_ai",
        lambda _documents: {
            "enabled": False,
            "available": False,
            "findings": [],
            "proposals": [],
        },
    )

    _boot, _authority, _candidates, intelligence = runtime_service._drive_context(
        include_ai=False
    )

    assert any(
        finding["type"] == "project_boot_incomplete"
        for finding in intelligence["findings"]
    )
    proposal = next(
        proposal for proposal in intelligence["proposals"]
        if proposal["finding_type"] == "workspace_review_required"
    )
    assert proposal["target"] == "PROJECT_BOOT.md"
    assert "external_action" not in proposal
    assert "target_content" not in proposal


def test_review_only_proposals_cannot_enter_authority_gate():
    import pytest
    from aipp_runner import approve_task, default_state, request_approval

    review_task = {
        "id": "INTEL-BOOT-REVIEW",
        "title": "PROJECT_BOOT.md incelemesi",
        "status": "PROPOSED",
        "change_action": "REVIEW",
        "source": {"finding_type": "workspace_review_required"},
    }

    state = default_state()
    state["task_lifecycle"]["FUTURE"].append(review_task)

    with pytest.raises(RuntimeError, match="yalnızca inceleme"):
        request_approval(state, review_task["id"])

    assert state["authority_gate"]["pending_approval"] is None
    assert state["task_lifecycle"]["NOW"] is None
    assert state["task_lifecycle"]["FUTURE"] == [review_task]

    # Defense in depth: direct approve_task calls must also be rejected,
    # even if a caller manually forges an in-memory pending-approval marker.
    state["authority_gate"]["pending_approval"] = review_task["id"]
    with pytest.raises(RuntimeError, match="yalnızca inceleme"):
        approve_task(state, review_task["id"], authority_log="APPROVED")

    assert state["task_lifecycle"]["NOW"] is None
    assert state["task_lifecycle"]["FUTURE"] == [review_task]

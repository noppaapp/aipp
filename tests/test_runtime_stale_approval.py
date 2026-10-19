import json
import runtime_service


def state(task_id):
    return {
        "ok": True,
        "status": "PROPOSAL_READY",
        "task_lifecycle": {
            "FUTURE": [{"id": task_id, "title": task_id, "status": "PROPOSED"}],
            "NOW": None,
            "COMPLETED": [],
        },
        "authority_gate": {"pending_approval": False},
    }


def test_old_proposal_refresh_does_not_approve_a_new_proposal(monkeypatch):
    monkeypatch.setenv("AIPP_RUNTIME_TOKEN", "test-runtime-token")
    monkeypatch.setenv("GDRIVE_FOLDER_ID", "folder")
    old_state = state("OLD")
    current_state = state("CURRENT")
    saved = []
    writes = []

    monkeypatch.setattr(runtime_service, "get_access_token", lambda: "access")
    monkeypatch.setattr(runtime_service, "read_session_state", lambda *_: old_state)
    monkeypatch.setattr(runtime_service, "_load_session_state", lambda: {"result": old_state})
    monkeypatch.setattr(runtime_service, "_save_session_state", lambda value: saved.append(value))
    monkeypatch.setattr(
        runtime_service, "_run_aipp",
        lambda *args, **kwargs: (0, current_state, json.dumps(current_state), ""),
    )
    monkeypatch.setattr(
        runtime_service, "write_session_state",
        lambda *args: writes.append(args[-1]),
    )
    monkeypatch.setattr(
        runtime_service, "write_authority_approval",
        lambda *args: (_ for _ in ()).throw(AssertionError("must not approve a different proposal")),
    )

    response = runtime_service.app.test_client().post(
        "/api/run", json={"command": "APPROVE", "task": "STALE"},
        headers={"X-AIPP-Runtime-Token": "test-runtime-token"}
    )

    assert response.status_code == 409
    body = response.get_json()
    assert body["refreshed"] is True
    assert body["result"]["task_lifecycle"]["FUTURE"][0]["id"] == "CURRENT"
    assert saved
    assert writes == [current_state]



def test_recover_stale_approved_action_revokes_old_approval_and_requires_new_id(monkeypatch):
    monkeypatch.setenv("AIPP_RUNTIME_TOKEN", "test-runtime-token")
    monkeypatch.setenv("GDRIVE_FOLDER_ID", "folder")
    stale = {
        "ok": True,
        "status": "NOW",
        "task_lifecycle": {
            "NOW": {"id": "OLD-BOOT", "title": "Old boot task", "status": "APPROVED",
                    "source": {"finding_type": "boot_version_mismatch"}},
            "FUTURE": [], "REFERENCE": [], "COMPLETED": [],
        },
        "authority_gate": {"pending_approval": None, "pending_proposal_id": None},
    }
    fresh = {
        "ok": True, "status": "PROPOSAL_READY",
        "task_lifecycle": {"NOW": None, "FUTURE": [
            {"id": "INTEL-NEW", "title": "Update PROJECT_BOOT", "status": "PROPOSED",
             "external_action": "GDRIVE_PROJECT_BOOT_TEXT",
             "target_file_id": "drive-id", "target_file_name": "PROJECT_BOOT.md",
             "target_expected_sha256": "expected", "target_content": "new content",
             "source": {"finding_type": "boot_version_mismatch"}},
        ], "REFERENCE": [], "COMPLETED": []},
        "authority_gate": {"pending_approval": None, "pending_proposal_id": None},
        "intelligence_queue": ["INTEL-NEW"],
        "project_intelligence": {"queue": [{"id": "INTEL-NEW", "title": "Update PROJECT_BOOT"}]},
    }
    saved, drive_writes = [], []
    monkeypatch.setattr(runtime_service, "get_access_token", lambda: "access")
    monkeypatch.setattr(runtime_service, "read_session_state", lambda *_: stale)
    monkeypatch.setattr(runtime_service, "_load_session_state", lambda: {"result": stale})
    monkeypatch.setattr(runtime_service, "_save_session_state", lambda value: saved.append(value))
    monkeypatch.setattr(runtime_service, "write_session_state", lambda *args: drive_writes.append(json.loads(json.dumps(args[-1]))))
    monkeypatch.setattr(
        runtime_service, "_run_aipp",
        lambda *args, **kwargs: (0, fresh, json.dumps(fresh), ""),
    )

    response = runtime_service.app.test_client().post(
        "/api/run",
        json={"command": "RECOVER_STALE_APPROVAL", "task": "OLD-BOOT"},
        headers={"X-AIPP-Runtime-Token": "test-runtime-token"},
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    new_task = result["task_lifecycle"]["FUTURE"][0]
    assert result["task_lifecycle"]["NOW"] is None
    assert result["task_lifecycle"]["REFERENCE"][0]["status"] == "STALE_APPROVAL_REVOKED"
    assert new_task["external_action"] == "GDRIVE_PROJECT_BOOT_TEXT"
    assert new_task["id"] != "INTEL-NEW"
    assert "yeniden onay gerekli" in new_task["title"]
    assert result["intelligence_queue"][0] == new_task["id"]
    assert saved and len(saved) == 2
    assert len(drive_writes) == 2
    # The old approval is durably revoked before workspace analysis starts.
    assert drive_writes[0]["task_lifecycle"]["NOW"] is None
    assert drive_writes[0]["status"] == "RECOVERY_IN_PROGRESS"
    assert drive_writes[0]["task_lifecycle"]["REFERENCE"][0]["status"] == "STALE_APPROVAL_REVOKED"
    assert drive_writes[1] == result


def test_failed_recovery_keeps_old_approval_revoked_in_canonical_state(monkeypatch):
    monkeypatch.setenv("AIPP_RUNTIME_TOKEN", "test-runtime-token")
    monkeypatch.setenv("GDRIVE_FOLDER_ID", "folder")
    stale = {
        "ok": True,
        "status": "NOW",
        "task_lifecycle": {
            "NOW": {"id": "OLD-BOOT", "title": "Old boot task", "status": "APPROVED",
                    "source": {"finding_type": "boot_version_mismatch"}},
            "FUTURE": [], "REFERENCE": [], "COMPLETED": [],
        },
        "authority_gate": {"pending_approval": None, "pending_proposal_id": None},
    }
    saved, drive_writes = [], []
    monkeypatch.setattr(runtime_service, "get_access_token", lambda: "access")
    monkeypatch.setattr(runtime_service, "read_session_state", lambda *_: stale)
    monkeypatch.setattr(runtime_service, "_load_session_state", lambda: {"result": stale})
    monkeypatch.setattr(runtime_service, "_save_session_state", lambda value: saved.append(value))
    monkeypatch.setattr(runtime_service, "write_session_state", lambda *args: drive_writes.append(json.loads(json.dumps(args[-1]))))
    monkeypatch.setattr(
        runtime_service, "_run_aipp",
        lambda *args, **kwargs: (1, None, "", "Drive scan failed"),
    )

    response = runtime_service.app.test_client().post(
        "/api/run",
        json={"command": "RECOVER_STALE_APPROVAL", "task": "OLD-BOOT"},
        headers={"X-AIPP-Runtime-Token": "test-runtime-token"},
    )

    assert response.status_code == 500
    assert len(drive_writes) == 2
    assert drive_writes[0]["status"] == "RECOVERY_IN_PROGRESS"
    failed = drive_writes[1]
    assert failed["status"] == "RECOVERY_FAILED"
    assert failed["task_lifecycle"]["NOW"] is None
    assert failed["task_lifecycle"]["REFERENCE"][0]["status"] == "STALE_APPROVAL_REVOKED"
    assert failed["authority_gate"]["pending_approval"] is None
    assert failed["recovery_job"]["status"] == "FAILED"



def test_recovery_context_reads_only_canonical_documents(monkeypatch):
    monkeypatch.setenv("GDRIVE_FOLDER_ID", "folder")
    monkeypatch.setenv("NOPPA_GDRIVE_FOLDER_ID", "noppa-folder")
    monkeypatch.setattr(runtime_service, "get_access_token", lambda: "access")
    monkeypatch.setattr(runtime_service, "find_project_boot", lambda *_: {"id": "boot-id"})
    monkeypatch.setattr(runtime_service, "find_authority_log", lambda *_: None)
    monkeypatch.setattr(
        runtime_service, "read_file_text",
        lambda _token, info: {
            "boot-id": "# PROJECT_BOOT v1.0",
            "protocol-id": "# AIPP v1.1.1",
        }.get(info["id"]),
    )
    monkeypatch.setattr(
        runtime_service, "list_workspace_tree",
        lambda *_: [{"id": "protocol-id", "name": "AIPP.md"}],
    )
    monkeypatch.setattr(
        runtime_service, "build_boot_version_update_proposal",
        lambda boot, file_id, protocol: {
            "target": "PROJECT_BOOT.md", "evidence": ["targeted evidence"]
        },
    )
    monkeypatch.setattr(
        runtime_service, "discover_task_candidates",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("recovery must not scan every workspace document")
        ),
    )
    monkeypatch.setattr(
        runtime_service, "analyze_documents",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("recovery must not analyze every workspace document")
        ),
    )

    boot, authority, candidates, intelligence = runtime_service._drive_context(
        include_ai=False, recovery_mode=True
    )

    assert boot == "# PROJECT_BOOT v1.0"
    assert authority == ""
    assert candidates == []
    assert intelligence["project_scopes"]["AIPP"]["status"] == "TARGETED_RECOVERY_SCAN"
    assert intelligence["project_scopes"]["NOPPA"]["status"] == "NOT_SCANNED_FOR_RECOVERY"
    assert len(intelligence["proposals"]) == 1

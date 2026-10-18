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

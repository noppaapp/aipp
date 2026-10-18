import panel.server as panel_server


def test_panel_delegates_commands_to_runtime_without_disk_state(monkeypatch, tmp_path):
    calls = []

    def fake_runtime_request(path, method="GET", payload=None):
        calls.append((path, method, payload))
        return {
            "ok": True,
            "status": "PROPOSAL_READY",
            "task_lifecycle": {"FUTURE": []},
        }

    monkeypatch.setattr(panel_server, "runtime_request", fake_runtime_request)
    monkeypatch.setattr(panel_server, "PANEL_TOKEN", "test-panel-token")

    client = panel_server.app.test_client()
    response = client.post(
        "/api/command",
        headers={"X-AIPP-Panel-Token": "test-panel-token"},
        json={"command": "BAŞLA"},
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "PROPOSAL_READY"
    assert calls == [
        (
            "/api/run",
            "POST",
            {"command": "BAŞLA", "task": None, "max_attempts": 3, "force_refresh": False},
        )
    ]
    assert not (tmp_path / "aipp_state.json").exists()


def test_panel_forwards_force_refresh_flag(monkeypatch):
    calls = []

    def fake_runtime_request(path, method="GET", payload=None):
        calls.append((path, method, payload))
        return {"ok": True, "status": "PROPOSAL_READY"}

    monkeypatch.setattr(panel_server, "runtime_request", fake_runtime_request)
    monkeypatch.setattr(panel_server, "PANEL_TOKEN", "")

    client = panel_server.app.test_client()
    response = client.post(
        "/api/command",
        json={"command": "BAŞLA", "force_refresh": True},
    )

    assert response.status_code == 200
    assert calls[0][2]["force_refresh"] is True


def test_panel_preserves_runtime_error_status(monkeypatch):
    def fake_runtime_request(path, method="GET", payload=None):
        raise panel_server.RuntimeRequestError(
            409,
            {"ok": False, "error": "No task in NOW state"},
        )

    monkeypatch.setattr(panel_server, "runtime_request", fake_runtime_request)
    monkeypatch.setattr(panel_server, "PANEL_TOKEN", "test-panel-token")

    client = panel_server.app.test_client()
    response = client.post(
        "/api/command",
        headers={"X-AIPP-Panel-Token": "test-panel-token"},
        json={"command": "CONTINUE", "task": "TASK-01"},
    )

    assert response.status_code == 409
    assert response.get_json() == {
        "ok": False,
        "error": "No task in NOW state",
    }


def test_panel_config_status_exposes_configuration_without_secrets(monkeypatch):
    monkeypatch.setattr(panel_server, "RUNTIME_URL", "https://runtime.example")
    monkeypatch.setattr(panel_server, "RUNTIME_TOKEN", "test-runtime-token")
    monkeypatch.setattr(panel_server, "PANEL_TOKEN", "test-panel-token")

    client = panel_server.app.test_client()
    response = client.get("/api/config-status", headers={"X-AIPP-Panel-Token": "test-panel-token"})

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["runtime_url_configured"] is True
    assert data["runtime_token_configured"] is True
    assert data["panel_token_configured"] is False
    assert data["runtime_token_fingerprint"] == panel_server.fingerprint("test-runtime-token")
    assert "test-runtime-token" not in response.get_data(as_text=True)



def test_operator_api_fails_closed_when_panel_token_is_missing(monkeypatch):
    monkeypatch.setattr(panel_server, "PANEL_TOKEN", "")
    client = panel_server.app.test_client()

    status = client.get("/api/status")
    command = client.post("/api/command", json={"command": "BAŞLA"})
    config = client.get("/api/config-status")

    assert status.status_code == 503
    assert command.status_code == 503
    assert config.status_code == 503
    assert "not configured" in status.get_json()["error"]


def test_operator_api_rejects_missing_or_invalid_panel_token(monkeypatch):
    monkeypatch.setattr(panel_server, "PANEL_TOKEN", "expected-secret")
    client = panel_server.app.test_client()

    missing = client.get("/api/status")
    invalid = client.post(
        "/api/command",
        headers={"X-AIPP-Panel-Token": "wrong-secret"},
        json={"command": "BAŞLA"},
    )

    assert missing.status_code == 401
    assert invalid.status_code == 401

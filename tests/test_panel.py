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
    monkeypatch.setattr(panel_server, "PANEL_TOKEN", "")

    client = panel_server.app.test_client()
    response = client.post(
        "/api/command",
        json={"command": "BAŞLA"},
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "PROPOSAL_READY"
    assert calls == [
        (
            "/api/run",
            "POST",
            {"command": "BAŞLA", "task": None, "max_attempts": 3},
        )
    ]
    assert not (tmp_path / "aipp_state.json").exists()


def test_panel_preserves_runtime_error_status(monkeypatch):
    def fake_runtime_request(path, method="GET", payload=None):
        raise panel_server.RuntimeRequestError(
            409,
            {"ok": False, "error": "No task in NOW state"},
        )

    monkeypatch.setattr(panel_server, "runtime_request", fake_runtime_request)
    monkeypatch.setattr(panel_server, "PANEL_TOKEN", "")

    client = panel_server.app.test_client()
    response = client.post(
        "/api/command",
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
    monkeypatch.setattr(panel_server, "PANEL_TOKEN", "")

    client = panel_server.app.test_client()
    response = client.get("/api/config-status")

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["runtime_url_configured"] is True
    assert data["runtime_token_configured"] is True
    assert data["panel_token_configured"] is False
    assert data["runtime_token_fingerprint"] == panel_server.fingerprint("test-runtime-token")
    assert "test-runtime-token" not in response.get_data(as_text=True)

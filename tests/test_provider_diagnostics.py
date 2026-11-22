import runtime_service


def test_diagnostics_reports_only_provider_presence(monkeypatch):
    monkeypatch.setenv("AIPP_RUNTIME_TOKEN", "runtime-secret")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-secret")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-secret")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("AIPP_SEMANTIC_ANALYSIS", "true")
    monkeypatch.setenv("NOPPA_GDRIVE_FOLDER_ID", "noppa-folder-id")

    response = runtime_service.app.test_client().get(
        "/api/diagnostics",
        headers={"X-AIPP-Runtime-Token": "runtime-secret"},
    )
    data = response.get_json()

    assert response.status_code == 200
    assert data["providers"] == {
        "gemini": True, "groq": False, "openrouter": True, "claude": False
    }
    assert data["configured_provider_count"] == 2
    assert data["semantic_analysis_enabled"] is True
    assert data["noppa_drive_configured"] is True
    serialized = response.get_data(as_text=True)
    for secret in ("runtime-secret", "gemini-secret", "openrouter-secret"):
        assert secret not in serialized


def test_diagnostics_fails_closed_without_runtime_token(monkeypatch):
    monkeypatch.delenv("AIPP_RUNTIME_TOKEN", raising=False)
    response = runtime_service.app.test_client().get("/api/diagnostics")
    assert response.status_code == 503
    assert response.get_json()["ok"] is False


def test_diagnostics_rejects_invalid_runtime_token(monkeypatch):
    monkeypatch.setenv("AIPP_RUNTIME_TOKEN", "runtime-secret")
    response = runtime_service.app.test_client().get(
        "/api/diagnostics",
        headers={"X-AIPP-Runtime-Token": "wrong"},
    )
    assert response.status_code == 401

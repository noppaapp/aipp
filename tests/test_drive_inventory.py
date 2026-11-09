import runtime_service


def test_inventory_requires_runtime_token(monkeypatch):
    monkeypatch.setenv("AIPP_RUNTIME_TOKEN", "test-runtime-token")
    response = runtime_service.app.test_client().get("/api/inventory")
    assert response.status_code == 401


def test_inventory_is_metadata_only_and_includes_both_roots(monkeypatch):
    monkeypatch.setenv("AIPP_RUNTIME_TOKEN", "test-runtime-token")
    monkeypatch.setenv("GDRIVE_FOLDER_ID", "aipp-root")
    monkeypatch.setenv("NOPPA_GDRIVE_FOLDER_ID", "noppa-root")
    monkeypatch.setattr(runtime_service, "get_access_token", lambda: "fake-access-token")
    calls = []

    def fake_inventory(token, folder_id):
        calls.append((token, folder_id))
        return {
            "root_folder_id": folder_id,
            "total_items": 1,
            "folder_count": 0,
            "file_count": 1,
            "sensitive_name_warning_count": 0,
            "items": [{"name": "brief.md", "path": "brief.md", "item_type": "file"}],
        }

    monkeypatch.setattr(runtime_service, "list_workspace_inventory", fake_inventory)
    response = runtime_service.app.test_client().get(
        "/api/inventory",
        headers={"X-AIPP-Runtime-Token": "test-runtime-token"},
    )

    data = response.get_json()
    assert response.status_code == 200
    assert data["mode"] == "READ_ONLY_METADATA"
    assert data["content_downloaded"] is False
    assert data["ai_analysis_performed"] is False
    assert data["drive_writes_performed"] is False
    assert [root["workspace"] for root in data["workspaces"]] == ["AIPP", "NOPPA"]
    assert calls == [("fake-access-token", "aipp-root"), ("fake-access-token", "noppa-root")]
    assert "attachment" in response.headers["Content-Disposition"]


def test_inventory_deduplicates_same_configured_root(monkeypatch):
    monkeypatch.setenv("AIPP_RUNTIME_TOKEN", "test-runtime-token")
    monkeypatch.setenv("GDRIVE_FOLDER_ID", "same-root")
    monkeypatch.setenv("NOPPA_GDRIVE_FOLDER_ID", "same-root")
    monkeypatch.setattr(runtime_service, "get_access_token", lambda: "fake-access-token")
    calls = []
    monkeypatch.setattr(
        runtime_service,
        "list_workspace_inventory",
        lambda token, folder_id: (
            calls.append(folder_id)
            or {
                "root_folder_id": folder_id,
                "total_items": 0,
                "folder_count": 0,
                "file_count": 0,
                "sensitive_name_warning_count": 0,
                "items": [],
            }
        ),
    )
    response = runtime_service.app.test_client().get(
        "/api/inventory",
        headers={"X-AIPP-Runtime-Token": "test-runtime-token"},
    )
    assert response.status_code == 200
    assert calls == ["same-root"]


def test_drive_inventory_builds_relative_paths_and_flags_sensitive_names(monkeypatch):
    import aipp_drive_runtime

    monkeypatch.setattr(
        aipp_drive_runtime,
        "list_workspace_tree",
        lambda token, root_id: [
            {"id": "folder-1", "name": "Drafts", "mimeType": aipp_drive_runtime.FOLDER_MIME, "parents": [root_id]},
            {"id": "file-1", "name": "brief.md", "mimeType": "text/markdown", "size": "120", "modifiedTime": "2026-11-01T10:00:00Z", "parents": ["folder-1"]},
            {"id": "file-2", "name": "service-account-credentials.json", "mimeType": "application/json", "parents": [root_id]},
        ],
    )

    result = aipp_drive_runtime.list_workspace_inventory("fake-token", "root")

    assert result["total_items"] == 3
    assert result["folder_count"] == 1
    assert result["file_count"] == 2
    by_name = {item["name"]: item for item in result["items"]}
    assert by_name["brief.md"]["path"] == "Drafts/brief.md"
    assert by_name["brief.md"]["size_bytes"] == 120
    assert by_name["service-account-credentials.json"]["sensitive_name_warning"] is True
    assert "content" not in by_name["brief.md"]

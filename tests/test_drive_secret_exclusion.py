import io
import zipfile

import aipp_drive_runtime as drive


def test_sensitive_drive_filename_is_skipped_before_download(monkeypatch):
    calls = []
    monkeypatch.setattr(drive, "_download_binary", lambda *args, **kwargs: calls.append(args) or b"must not be read")
    result = drive.read_file_text(
        "fake-token",
        {"id": "secret-file", "name": "credentials.json", "mimeType": "application/json"},
    )
    assert result is None
    assert calls == []


def test_sensitive_names_are_skipped_before_any_supported_content_request(monkeypatch):
    calls = []
    monkeypatch.setattr(drive, "_request", lambda *args, **kwargs: calls.append(args) or b"must not be exported")
    monkeypatch.setattr(drive, "_download_binary", lambda *args, **kwargs: calls.append(args) or b"must not be downloaded")
    for mime in ("application/json", "text/plain", "application/pdf", drive.GOOGLE_DOC_MIME):
        assert drive.read_file_text(
            "fake-token",
            {"id": "secret-file", "name": "oauth-client-secret.json", "mimeType": mime, "size": "100"},
        ) is None
    assert calls == []


def test_zip_reader_excludes_sensitive_member_names_but_keeps_project_docs():
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("credentials.json", '{"client_secret":"do-not-read"}')
        archive.writestr("docs/brief.md", "Project brief content")
    extracted = drive._read_zip(archive_bytes.getvalue())
    assert "client_secret" not in extracted
    assert "credentials.json" not in extracted
    assert "Project brief content" in extracted


def test_drive_runtime_main_publishes_candidates_from_its_existing_discovery(monkeypatch):
    import aipp_drive_runtime as drive

    calls = {"discover": 0, "publish": []}
    boot_info = {"id": "boot-id", "name": "PROJECT_BOOT.md"}
    candidates = [{"id": "task-file", "name": "tasks.md", "task_ids": ["TASK-01"]}]

    monkeypatch.setenv("GDRIVE_FOLDER_ID", "folder")
    monkeypatch.setattr(drive, "get_access_token", lambda: "access")
    monkeypatch.setattr(drive, "find_project_boot", lambda *_: boot_info)
    monkeypatch.setattr(drive, "read_file_text", lambda *_: "# PROJECT_BOOT: AIPP")
    monkeypatch.setattr(drive, "publish_boot_to_runtime_env", lambda _text: None)
    monkeypatch.setattr(drive, "find_authority_log", lambda *_: None)
    monkeypatch.setattr(drive, "publish_authority_to_runtime_env", lambda _text: None)

    def discover(*_args, **_kwargs):
        calls["discover"] += 1
        return candidates

    monkeypatch.setattr(drive, "discover_task_candidates", discover)
    monkeypatch.setattr(
        drive,
        "publish_task_candidates_to_runtime_env",
        lambda value: calls["publish"].append(value),
    )

    drive.main()

    assert calls["discover"] == 1
    assert calls["publish"] == [candidates]

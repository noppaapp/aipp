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

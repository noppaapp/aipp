import hashlib
import json
import pytest
from runtime import gdrive_target


def fixture(monkeypatch, current_text="# old\\n"):
    monkeypatch.setenv("GDRIVE_FOLDER_ID", "folder-identifier-123")
    info = {"id": "drive-file-identifier-123", "name": "PROJECT_BOOT.md",
            "mimeType": "text/markdown", "parents": ["folder-identifier-123"]}
    current = {"text": current_text}
    calls = []
    monkeypatch.setattr(gdrive_target, "get_access_token", lambda: "token")
    monkeypatch.setattr(gdrive_target, "list_workspace_tree", lambda token, folder: [info])
    monkeypatch.setattr(gdrive_target, "read_file_text", lambda token, file_info: current["text"])
    def fake_request(url, method="GET", data=None, token=None, content_type=None, headers=None, return_headers=False):
        calls.append({"method": method, "headers": headers or {}, "data": data})
        if return_headers:
            meta = {"id": info["id"], "name": info["name"], "mimeType": info["mimeType"],
                    "trashed": False, "capabilities": {"canEdit": True}}
            return json.dumps(meta).encode(), {"ETag": '"revision-1"'}
        if method == "PATCH":
            current["text"] = data.decode("utf-8")
        return b"{}"
    monkeypatch.setattr(gdrive_target, "_request", fake_request)
    return info, current, calls


def test_updates_canonical_boot_conditionally_and_verifies(monkeypatch):
    info, current, calls = fixture(monkeypatch)
    old = current["text"]
    new = "# approved update\\n"
    result = gdrive_target.apply_project_boot_text("TASK-42", info["id"], "PROJECT_BOOT.md",
                                                   hashlib.sha256(old.encode()).hexdigest(), new)
    assert current["text"] == new
    assert result["verified"] is True
    assert result["content_sha256"] == hashlib.sha256(new.encode()).hexdigest()
    assert next(c for c in calls if c["method"] == "PATCH")["headers"]["If-Match"] == '"revision-1"'


def test_rejects_stale_hash_without_writing(monkeypatch):
    info, _, calls = fixture(monkeypatch)
    with pytest.raises(gdrive_target.DriveTargetHalt, match="changed after proposal"):
        gdrive_target.apply_project_boot_text("TASK-42", info["id"], "PROJECT_BOOT.md", "0" * 64, "# new\\n")
    assert not any(c["method"] == "PATCH" for c in calls)


def test_rejects_wrong_target_duplicate_boot_and_missing_etag(monkeypatch):
    info, current, calls = fixture(monkeypatch)
    with pytest.raises(gdrive_target.DriveTargetHalt, match="only permits"):
        gdrive_target.apply_project_boot_text("TASK-42", info["id"], "OTHER.md",
                                              hashlib.sha256(current["text"].encode()).hexdigest(), "# new\\n")
    assert not calls
    monkeypatch.setattr(gdrive_target, "list_workspace_tree",
                        lambda token, folder: [info, dict(info, id="another-drive-file-123")])
    with pytest.raises(gdrive_target.DriveTargetHalt, match="exactly one"):
        gdrive_target.apply_project_boot_text("TASK-42", info["id"], "PROJECT_BOOT.md",
                                              hashlib.sha256(current["text"].encode()).hexdigest(), "# new\\n")
    monkeypatch.setattr(gdrive_target, "list_workspace_tree", lambda token, folder: [info])
    original = gdrive_target._request
    def no_etag(*args, **kwargs):
        result = original(*args, **kwargs)
        return (result[0], {}) if kwargs.get("return_headers") else result
    monkeypatch.setattr(gdrive_target, "_request", no_etag)
    with pytest.raises(gdrive_target.DriveTargetHalt, match="ETag"):
        gdrive_target.apply_project_boot_text("TASK-42", info["id"], "PROJECT_BOOT.md",
                                              hashlib.sha256(current["text"].encode()).hexdigest(), "# new\\n")
    assert not any(c["method"] == "PATCH" for c in calls)

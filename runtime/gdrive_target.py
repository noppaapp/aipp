"""Fail-closed updater for the canonical plain-text Google Drive PROJECT_BOOT.md."""
import hashlib
import json
import os
import re
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from aipp_drive_runtime import DRIVE_API, get_access_token, list_workspace_tree, read_file_text

PROJECT_BOOT_NAME = "PROJECT_BOOT.md"
ALLOWED_MIME_TYPES = {"text/plain", "text/markdown", "text/x-markdown"}
MAX_CONTENT_BYTES = 1_000_000
FILE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,200}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class DriveTargetHalt(RuntimeError):
    pass


def _request(url, method="GET", data=None, token=None, content_type=None, headers=None, return_headers=False):
    request_headers = {"Authorization": f"Bearer {token}"} if token else {}
    if content_type:
        request_headers["Content-Type"] = content_type
    request_headers.update(headers or {})
    with urlopen(Request(url, data=data, headers=request_headers, method=method)) as response:
        body = response.read()
        return (body, response.headers) if return_headers else body


def apply_project_boot_text(task_id, file_id, file_name, expected_sha256, content):
    """Write only exact approved text; require current hash, ETag and read-back."""
    folder_id = os.environ.get("GDRIVE_FOLDER_ID", "").strip()
    if not folder_id:
        raise DriveTargetHalt("HALT: GDRIVE_FOLDER_ID is empty")
    if file_name != PROJECT_BOOT_NAME:
        raise DriveTargetHalt("HALT: Google Drive action only permits PROJECT_BOOT.md")
    if not isinstance(file_id, str) or not FILE_ID_RE.fullmatch(file_id):
        raise DriveTargetHalt("HALT: invalid Google Drive target file id")
    if not isinstance(expected_sha256, str) or not SHA_RE.fullmatch(expected_sha256):
        raise DriveTargetHalt("HALT: approved expected content SHA-256 is required")
    if not isinstance(content, str) or not content.strip():
        raise DriveTargetHalt("HALT: approved target content must be non-empty")
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_CONTENT_BYTES:
        raise DriveTargetHalt("HALT: target content exceeds the 1 MB safety limit")

    token = get_access_token()
    files = list_workspace_tree(token, folder_id)
    boots = [f for f in files if f.get("name") == PROJECT_BOOT_NAME]
    if len(boots) != 1:
        raise DriveTargetHalt(f"HALT: expected exactly one {PROJECT_BOOT_NAME}; found {len(boots)}")
    info = boots[0]
    if info.get("id") != file_id:
        raise DriveTargetHalt("HALT: approved id is not the canonical PROJECT_BOOT.md")
    if info.get("mimeType") not in ALLOWED_MIME_TYPES:
        raise DriveTargetHalt("HALT: PROJECT_BOOT.md must be a plain-text or Markdown file")
    current = read_file_text(token, info)
    if current is None:
        raise DriveTargetHalt("HALT: canonical PROJECT_BOOT.md could not be read")
    current_hash = hashlib.sha256(current.encode("utf-8")).hexdigest()
    if current_hash != expected_sha256:
        raise DriveTargetHalt("HALT: PROJECT_BOOT.md changed after proposal creation; refresh and request approval again")
    new_hash = hashlib.sha256(encoded).hexdigest()
    if new_hash == current_hash:
        raise DriveTargetHalt("HALT: approved content is identical to the current file")

    metadata_url = f"{DRIVE_API}/files/{file_id}?{urlencode({'fields': 'id,name,mimeType,trashed,capabilities(canEdit)', 'supportsAllDrives': 'true'})}"
    try:
        raw, response_headers = _request(metadata_url, token=token, return_headers=True)
    except HTTPError as exc:
        raise DriveTargetHalt(f"HALT: Drive metadata revalidation failed (HTTP {exc.code})") from exc
    try:
        metadata = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise DriveTargetHalt("HALT: invalid Drive metadata response") from exc
    if (metadata.get("id") != file_id or metadata.get("name") != PROJECT_BOOT_NAME
            or metadata.get("mimeType") not in ALLOWED_MIME_TYPES or metadata.get("trashed") is True
            or metadata.get("capabilities", {}).get("canEdit") is not True):
        raise DriveTargetHalt("HALT: Drive target metadata no longer matches the approved file")
    etag = response_headers.get("ETag") or response_headers.get("etag")
    if not etag:
        raise DriveTargetHalt("HALT: Drive supplied no ETag; refusing a non-conditional write")

    upload_url = f"https://www.googleapis.com/upload/drive/v3/files/{file_id}?{urlencode({'uploadType': 'media', 'supportsAllDrives': 'true'})}"
    try:
        _request(upload_url, method="PATCH", data=encoded, token=token,
                 content_type=info.get("mimeType"), headers={"If-Match": etag})
    except HTTPError as exc:
        if exc.code in {409, 412}:
            raise DriveTargetHalt("HALT: PROJECT_BOOT.md changed during approval; conditional write rejected") from exc
        raise DriveTargetHalt(f"HALT: Google Drive write failed (HTTP {exc.code})") from exc

    verified = read_file_text(token, info)
    if verified is None or hashlib.sha256(verified.encode("utf-8")).hexdigest() != new_hash:
        raise DriveTargetHalt("HALT: Drive write completed but read-back verification failed")
    return {"action": "GDRIVE_PROJECT_BOOT_TEXT", "task_id": task_id, "file_id": file_id,
            "file_name": PROJECT_BOOT_NAME, "previous_content_sha256": current_hash,
            "content_sha256": new_hash, "verified": True}

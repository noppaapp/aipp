import json
import uuid
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from aipp_drive_runtime import DRIVE_API, _request
from aipp_project_bootstrap import parse_project_boot_text


class WriteBackError(RuntimeError):
    pass


def mutate_project_boot_task_status(text, task_id, new_status="COMPLETED"):
    """Return canonical PROJECT_BOOT text with exactly one task status changed."""
    if new_status not in {"COMPLETED"}:
        raise WriteBackError(f"Unsupported canonical completion status: {new_status}")
    target = str(task_id).strip()
    if not target:
        raise WriteBackError("task_id is required")

    parsed = parse_project_boot_text(text)
    matches = [task for task in parsed["tasks"] if task.get("id") == target]
    if len(matches) != 1:
        raise WriteBackError(f"Canonical PROJECT_BOOT must contain exactly one task: {target}")
    if matches[0].get("status") == "COMPLETED":
        return text

    lines = text.splitlines(keepends=True)
    changed = 0
    for index, line in enumerate(lines):
        if not line.lstrip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        if cells[0].strip("*` ") == target:
            newline = "\n" if line.endswith("\n") else ""
            prefix = line[: len(line) - len(line.lstrip())]
            lines[index] = prefix + "| " + " | ".join([cells[0], cells[1], "COMPLETED", cells[3]]) + " |" + newline
            changed += 1
    if changed != 1:
        raise WriteBackError(f"Could not mutate canonical task row: {target}")

    updated = "".join(lines)
    reparsed = parse_project_boot_text(updated)
    final = [task for task in reparsed["tasks"] if task.get("id") == target]
    if len(final) != 1 or final[0].get("status") != "COMPLETED":
        raise WriteBackError(f"Canonical PROJECT_BOOT validation failed after mutation: {target}")
    return updated


def _multipart_upload(token, metadata, media_bytes, media_type="application/octet-stream", method="POST", file_id=None):
    boundary = "aipp-" + uuid.uuid4().hex
    body = (
        f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
        + json.dumps(metadata, ensure_ascii=False)
        + f"\r\n--{boundary}\r\nContent-Type: {media_type}\r\n\r\n"
    ).encode("utf-8") + media_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")
    if method == "POST":
        endpoint = f"{DRIVE_API}/files?{urlencode({'uploadType': 'multipart', 'supportsAllDrives': 'true'})}"
    else:
        endpoint = f"https://www.googleapis.com/upload/drive/v3/files/{file_id}?{urlencode({'uploadType': 'multipart', 'supportsAllDrives': 'true'})}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": f"multipart/related; boundary={boundary}"}
    request = Request(endpoint, data=body, headers=headers, method=method)
    with urlopen(request) as response:
        return json.loads(response.read().decode("utf-8"))


def upload_artifact(token, parent_folder_id, artifact_path, task_id):
    path = Path(artifact_path)
    if not path.exists() or not path.is_file():
        raise WriteBackError(f"Artifact missing: {path}")
    metadata = {"name": path.name, "parents": [parent_folder_id], "description": f"AIPP artifact for {task_id}"}
    return _multipart_upload(token, metadata, path.read_bytes(), "application/json")


def upload_project_boot(token, boot_file_id, updated_text):
    return _multipart_upload(token, {}, updated_text.encode("utf-8"), "text/markdown", method="PATCH", file_id=boot_file_id)


def verify_remote_project_boot(token, boot_file_id, task_id):
    endpoint = f"{DRIVE_API}/files/{boot_file_id}?{urlencode({'alt': 'media', 'supportsAllDrives': 'true'})}"
    raw = _request(endpoint, token=token)
    text = raw.decode("utf-8-sig", errors="replace")
    parsed = parse_project_boot_text(text)
    matches = [task for task in parsed["tasks"] if task.get("id") == task_id]
    return len(matches) == 1 and matches[0].get("status") == "COMPLETED"


def commit_task_completion(token, boot_file_id, artifact_parent_folder_id, task_id, artifact_path, current_boot_text):
    """Publish artifacts first, then canonical completion, then read back canonical state."""
    updated_boot = mutate_project_boot_task_status(current_boot_text, task_id)
    artifact = upload_artifact(token, artifact_parent_folder_id, artifact_path, task_id)
    try:
        upload_project_boot(token, boot_file_id, updated_boot)
    except Exception as exc:
        raise WriteBackError(f"Artifact published but canonical PROJECT_BOOT write-back failed: {exc}") from exc
    if not verify_remote_project_boot(token, boot_file_id, task_id):
        raise WriteBackError(f"Canonical PROJECT_BOOT read-back verification failed: {task_id}")
    return {"task_id": task_id, "artifact_id": artifact.get("id"), "canonical_status": "COMPLETED"}

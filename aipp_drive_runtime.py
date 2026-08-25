import io
import os
import re
import zipfile
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

DRIVE_API = "https://www.googleapis.com/drive/v3"
PROJECT_BOOT = "PROJECT_BOOT.md"
GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
GOOGLE_SHEET_MIME = "application/vnd.google-apps.spreadsheet"
GOOGLE_SLIDES_MIME = "application/vnd.google-apps.presentation"
FOLDER_MIME = "application/vnd.google-apps.folder"
PDF_MIME = "application/pdf"
ZIP_MIME = "application/zip"
TEXT_MIME_TYPES = {"text/plain", "text/markdown", "text/csv", "application/json", "application/xml", "application/x-yaml", "text/yaml"}
ZIP_TEXT_EXTENSIONS = {".md", ".markdown", ".txt", ".json", ".yaml", ".yml", ".csv", ".xml", ".py", ".js", ".ts", ".toml"}
TASK_ID_RE = re.compile(r"\bTASK[-_ ]?\d+\b", re.IGNORECASE)


def _request(url, method="GET", data=None, token=None, content_type=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    if content_type:
        headers["Content-Type"] = content_type
    with urlopen(Request(url, data=data, headers=headers, method=method)) as response:
        return response.read()


def get_credentials():
    import json
    raw = os.environ.get("GDRIVE_CREDENTIALS", "").strip()
    if not raw:
        raise RuntimeError("HALT: GDRIVE_CREDENTIALS is empty")
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            client_id = data.get("client_id") or data.get("installed", {}).get("client_id") or data.get("web", {}).get("client_id")
            client_secret = data.get("client_secret") or data.get("installed", {}).get("client_secret") or data.get("web", {}).get("client_secret")
            if client_id and client_secret:
                return client_id, client_secret
    except json.JSONDecodeError:
        pass
    parts = raw.replace(";", " ").split()
    if len(parts) >= 2:
        return parts[0], parts[1]
    raise RuntimeError("HALT: GDRIVE_CREDENTIALS must contain Client ID and Client Secret")


def get_access_token():
    import json
    client_id, client_secret = get_credentials()
    refresh_token = os.environ.get("GCP_REFRESH_TOKEN", "").strip()
    if not refresh_token:
        raise RuntimeError("HALT: GCP_REFRESH_TOKEN is empty")
    payload = urlencode({"client_id": client_id, "client_secret": client_secret, "refresh_token": refresh_token, "grant_type": "refresh_token"}).encode()
    result = json.loads(_request("https://oauth2.googleapis.com/token", "POST", payload, content_type="application/x-www-form-urlencoded"))
    if "access_token" not in result:
        raise RuntimeError("HALT: Google OAuth did not return an access token")
    return result["access_token"]


def list_workspace_children(token, folder_id):
    import json
    query = f"'{folder_id}' in parents and trashed=false"
    fields = "files(id,name,mimeType,size,modifiedTime,parents,capabilities(canDownload)),nextPageToken"
    files, page_token = [], None
    while True:
        params_data = {"q": query, "fields": fields, "pageSize": 1000, "supportsAllDrives": "true", "includeItemsFromAllDrives": "true", "orderBy": "modifiedTime desc"}
        if page_token:
            params_data["pageToken"] = page_token
        result = json.loads(_request(f"{DRIVE_API}/files?{urlencode(params_data)}", token=token))
        files.extend(result.get("files", []))
        page_token = result.get("nextPageToken")
        if not page_token:
            return files


def list_workspace_tree(token, root_folder_id):
    discovered, visited, pending = [], set(), [root_folder_id]
    while pending:
        folder_id = pending.pop()
        if folder_id in visited:
            continue
        visited.add(folder_id)
        children = list_workspace_children(token, folder_id)
        discovered.extend(children)
        pending.extend(child["id"] for child in children if child.get("mimeType") == FOLDER_MIME)
    print(f"DRIVE_TREE_DISCOVERY folders={len(visited)} files={len(discovered)}")
    return discovered


def find_project_boot(token, folder_id):
    import json
    # PROJECT_BOOT.md is canonical regardless of which nested Workspace folder contains it.
    # The configured Drive folder is the workspace root, not necessarily the direct parent.
    files = [file_info for file_info in list_workspace_tree(token, folder_id) if file_info.get("name") == PROJECT_BOOT]
    if not files:
        return None
    if len(files) > 1:
        ids = ",".join(file_info.get("id", "") for file_info in files)
        raise RuntimeError(f"HALT: multiple {PROJECT_BOOT} files found in configured Drive workspace: {ids}")
    file_info = files[0]
    print(f"DRIVE_PROJECT_BOOT_FOUND id={file_info.get('id')} mimeType={file_info.get('mimeType')} modifiedTime={file_info.get('modifiedTime')}")
    return file_info


def _download_binary(token, file_id):
    endpoint = f"{DRIVE_API}/files/{file_id}?{urlencode({'alt': 'media', 'supportsAllDrives': 'true'})}"
    return _request(endpoint, token=token)


def _read_pdf(raw):
    if PdfReader is None:
        return None
    try:
        reader = PdfReader(io.BytesIO(raw))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        return None


def _read_zip(raw):
    try:
        chunks = []
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            for info in archive.infolist():
                if info.is_dir() or Path(info.filename).suffix.lower() not in ZIP_TEXT_EXTENSIONS or info.file_size > 2_000_000:
                    continue
                try:
                    text = archive.read(info).decode("utf-8-sig", errors="replace")
                    chunks.append(f"\n--- {info.filename} ---\n{text}")
                except Exception:
                    continue
        return "".join(chunks) if chunks else None
    except (zipfile.BadZipFile, OSError):
        return None


def read_file_text(token, file_info):
    file_id, mime = file_info["id"], file_info.get("mimeType")
    if mime == FOLDER_MIME:
        return None
    if mime in {GOOGLE_DOC_MIME, GOOGLE_SLIDES_MIME}:
        endpoint = f"{DRIVE_API}/files/{file_id}/export?{urlencode({'mimeType': 'text/plain', 'supportsAllDrives': 'true'})}"
        try:
            return _request(endpoint, token=token).decode("utf-8-sig", errors="replace")
        except HTTPError:
            return None
    if mime == GOOGLE_SHEET_MIME:
        endpoint = f"{DRIVE_API}/files/{file_id}/export?{urlencode({'mimeType': 'text/csv', 'supportsAllDrives': 'true'})}"
        try:
            return _request(endpoint, token=token).decode("utf-8-sig", errors="replace")
        except HTTPError:
            return None
    if mime in TEXT_MIME_TYPES:
        try:
            return _download_binary(token, file_id).decode("utf-8-sig", errors="replace")
        except (HTTPError, UnicodeDecodeError):
            return None
    if mime == PDF_MIME:
        try:
            return _read_pdf(_download_binary(token, file_info["id"]))
        except HTTPError:
            return None
    if mime == ZIP_MIME:
        try:
            return _read_zip(_download_binary(token, file_info["id"]))
        except HTTPError:
            return None
    return None


def download_project_boot(token, file_info, destination=PROJECT_BOOT):
    text = read_file_text(token, file_info)
    if text is None:
        raise RuntimeError("HALT: PROJECT_BOOT.md could not be read from Google Drive")
    Path(destination).write_text(text, encoding="utf-8")
    print(f"DRIVE_CANONICAL_STATE_MATERIALIZED file={destination} source_id={file_info['id']}")
    return text


def discover_task_candidates(token, folder_id):
    files = list_workspace_tree(token, folder_id)
    candidates, readable, unreadable, scanned_files = [], 0, 0, 0
    mime_counts = {}
    for file_info in files:
        mime = file_info.get("mimeType", "")
        mime_counts[mime] = mime_counts.get(mime, 0) + 1
        if mime == FOLDER_MIME:
            continue
        scanned_files += 1
        text = read_file_text(token, file_info)
        if text is not None:
            readable += 1
        else:
            unreadable += 1
        haystack = f"{file_info.get('name', '')}\n{text or ''}"
        ids = sorted({m.upper().replace("_", "-").replace(" ", "-") for m in TASK_ID_RE.findall(haystack)})
        if ids:
            candidates.append({"id": file_info["id"], "name": file_info.get("name"), "mimeType": mime, "task_ids": ids, "parents": file_info.get("parents", [])})
            print(f"DRIVE_TASK_CANDIDATE name={file_info.get('name')} task_ids={','.join(ids)} mimeType={mime}")
    mime_summary = ",".join(f"{key}:{value}" for key, value in sorted(mime_counts.items()))
    print(f"DRIVE_DISCOVERY files={scanned_files} readable={readable} unreadable={unreadable} task_candidates={len(candidates)} mime_types={mime_summary}")
    return candidates


def main():
    token = get_access_token()
    folder_id = os.environ.get("GDRIVE_FOLDER_ID", "").strip()
    if not folder_id:
        raise RuntimeError("HALT: GDRIVE_FOLDER_ID is empty")
    boot_info = find_project_boot(token, folder_id)
    if not boot_info:
        raise RuntimeError("HALT: PROJECT_BOOT.md not found in configured Drive folder")
    download_project_boot(token, boot_info)
    discover_task_candidates(token, folder_id)
    print("DRIVE_CANONICAL_STATE_READY source=PROJECT_BOOT.md runtime_state=purely_ephemeral")


if __name__ == "__main__":
    main()

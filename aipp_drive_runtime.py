import io
import json
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
STATE_FILE = "aipp_state.json"
GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
GOOGLE_SHEET_MIME = "application/vnd.google-apps.spreadsheet"
GOOGLE_SLIDES_MIME = "application/vnd.google-apps.presentation"
FOLDER_MIME = "application/vnd.google-apps.folder"
PDF_MIME = "application/pdf"
ZIP_MIME = "application/zip"
TEXT_MIME_TYPES = {
    "text/plain": "text/plain",
    "text/markdown": "text/plain",
    "text/csv": "text/plain",
    "application/json": "text/plain",
    "application/xml": "text/plain",
    "application/x-yaml": "text/plain",
    "text/yaml": "text/plain",
}
ZIP_TEXT_EXTENSIONS = {".md", ".markdown", ".txt", ".json", ".yaml", ".yml", ".csv", ".xml", ".py", ".js", ".ts", ".toml"}
TASK_ID_RE = re.compile(r"\bTASK[-_ ]?\d+\b", re.IGNORECASE)


def _request(url, method="GET", data=None, token=None, content_type=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if content_type:
        headers["Content-Type"] = content_type
    req = Request(url, data=data, headers=headers, method=method)
    with urlopen(req) as response:
        return response.read()


def get_credentials():
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
    client_id, client_secret = get_credentials()
    refresh_token = os.environ.get("GCP_REFRESH_TOKEN", "").strip()
    if not refresh_token:
        raise RuntimeError("HALT: GCP_REFRESH_TOKEN is empty")
    payload = urlencode({"client_id": client_id, "client_secret": client_secret, "refresh_token": refresh_token, "grant_type": "refresh_token"}).encode()
    raw = _request("https://oauth2.googleapis.com/token", method="POST", data=payload, content_type="application/x-www-form-urlencoded")
    result = json.loads(raw)
    if "access_token" not in result:
        raise RuntimeError("HALT: Google OAuth did not return an access token")
    return result["access_token"]


def find_state_file(token, folder_id):
    query = f"name='{STATE_FILE}' and '{folder_id}' in parents and trashed=false"
    params = urlencode({"q": query, "fields": "files(id,name,mimeType,size,capabilities(canDownload),driveId,webContentLink)", "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"})
    result = json.loads(_request(f"{DRIVE_API}/files?{params}", token=token))
    files = result.get("files", [])
    if files:
        f = files[0]
        print(f"DRIVE_FILE_FOUND id={f.get('id')} mimeType={f.get('mimeType')} size={f.get('size')} canDownload={f.get('capabilities', {}).get('canDownload')} driveId={f.get('driveId')} webContentLink={bool(f.get('webContentLink'))}")
        return f
    return None


def list_workspace_children(token, folder_id):
    query = f"'{folder_id}' in parents and trashed=false"
    fields = "files(id,name,mimeType,size,modifiedTime,parents,capabilities(canDownload)),nextPageToken"
    files = []
    page_token = None
    while True:
        params_data = {"q": query, "fields": fields, "pageSize": 1000, "supportsAllDrives": "true", "includeItemsFromAllDrives": "true", "orderBy": "modifiedTime desc"}
        if page_token:
            params_data["pageToken"] = page_token
        params = urlencode(params_data)
        result = json.loads(_request(f"{DRIVE_API}/files?{params}", token=token))
        files.extend(result.get("files", []))
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return files


def list_workspace_tree(token, root_folder_id):
    discovered = []
    visited = set()
    pending = [root_folder_id]
    while pending:
        folder_id = pending.pop()
        if folder_id in visited:
            continue
        visited.add(folder_id)
        children = list_workspace_children(token, folder_id)
        discovered.extend(children)
        for child in children:
            if child.get("mimeType") == FOLDER_MIME:
                pending.append(child["id"])
    print(f"DRIVE_TREE_DISCOVERY folders={len(visited)} files={len(discovered)}")
    return discovered


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
                if info.is_dir() or Path(info.filename).suffix.lower() not in ZIP_TEXT_EXTENSIONS:
                    continue
                if info.file_size > 2_000_000:
                    continue
                try:
                    text = archive.read(info).decode("utf-8-sig", errors="replace")
                except Exception:
                    continue
                chunks.append(f"\n--- {info.filename} ---\n{text}")
        return "".join(chunks) if chunks else None
    except (zipfile.BadZipFile, OSError):
        return None


def read_file_text(token, file_info):
    file_id = file_info["id"]
    mime = file_info.get("mimeType")
    if mime == FOLDER_MIME:
        return None
    if mime == GOOGLE_DOC_MIME:
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
    if mime == GOOGLE_SLIDES_MIME:
        endpoint = f"{DRIVE_API}/files/{file_id}/export?{urlencode({'mimeType': 'text/plain', 'supportsAllDrives': 'true'})}"
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
            return _read_pdf(_download_binary(token, file_id))
        except HTTPError:
            return None
    if mime == ZIP_MIME:
        try:
            return _read_zip(_download_binary(token, file_id))
        except HTTPError:
            return None
    return None


def discover_task_candidates(token, folder_id):
    files = list_workspace_tree(token, folder_id)
    candidates = []
    readable = 0
    unreadable = 0
    mime_counts = {}
    scanned_files = 0
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
        ids = sorted({match.upper().replace("_", "-").replace(" ", "-") for match in TASK_ID_RE.findall(haystack)})
        if ids:
            candidate = {"id": file_info["id"], "name": file_info.get("name"), "mimeType": mime, "task_ids": ids, "parents": file_info.get("parents", [])}
            candidates.append(candidate)
            print(f"DRIVE_TASK_CANDIDATE name={file_info.get('name')} task_ids={','.join(ids)} mimeType={mime}")
    mime_summary = ",".join(f"{key}:{value}" for key, value in sorted(mime_counts.items()))
    print(f"DRIVE_DISCOVERY files={scanned_files} readable={readable} unreadable={unreadable} task_candidates={len(candidates)} mime_types={mime_summary}")
    return candidates


def reconcile_discovered_tasks(state, candidates):
    """Map discovered task evidence into FUTURE without crossing the Authority Gate.

    Discovery is allowed to propose work, but it must never move a discovered task to NOW.
    Existing NOW/COMPLETED/BLOCKED/DEFERRED/REFERENCE entries remain authoritative.
    """
    lifecycle = state.setdefault("task_lifecycle", {})
    for key, default in {
        "NOW": None,
        "DEFERRED": [],
        "BLOCKED": [],
        "FUTURE": [],
        "REFERENCE": [],
        "COMPLETED": [],
    }.items():
        lifecycle.setdefault(key, default)

    existing_ids = set()
    for bucket in ("NOW", "DEFERRED", "BLOCKED", "FUTURE", "REFERENCE", "COMPLETED"):
        items = lifecycle.get(bucket)
        if isinstance(items, dict):
            items = [items]
        for item in items or []:
            if isinstance(item, dict) and item.get("id"):
                existing_ids.add(item["id"])

    added = []
    for candidate in candidates:
        for task_id in candidate.get("task_ids", []):
            if task_id in existing_ids:
                continue
            proposal = {
                "id": task_id,
                "title": f"Discovered task {task_id}",
                "status": "PROPOSED",
                "source": {
                    "type": "WORKSPACE_DISCOVERY",
                    "file_id": candidate.get("id"),
                    "file_name": candidate.get("name"),
                    "mimeType": candidate.get("mimeType"),
                },
                "proposal_reason": "Task identifier discovered during canonical Workspace scan",
            }
            lifecycle["FUTURE"].append(proposal)
            existing_ids.add(task_id)
            added.append(task_id)

    if added:
        state["status"] = "PROPOSAL_READY"
        state.setdefault("authority_gate", {})["last_action"] = "WORKSPACE_DISCOVERY_PROPOSALS"
        print(f"WORKSPACE_TASK_RECONCILIATION discovered={len(added)} added_to=FUTURE ids={','.join(added)}")
    else:
        print("WORKSPACE_TASK_RECONCILIATION discovered=0 added_to=FUTURE ids=none")
    return state


def read_drive_state(token, file_info):
    file_id = file_info["id"]
    if file_info.get("mimeType") == GOOGLE_DOC_MIME:
        params = urlencode({"mimeType": "text/plain", "supportsAllDrives": "true"})
        endpoint = f"{DRIVE_API}/files/{file_id}/export?{params}"
        error_label = "Google Docs export"
    else:
        params = urlencode({"alt": "media", "supportsAllDrives": "true"})
        endpoint = f"{DRIVE_API}/files/{file_id}?{params}"
        error_label = "Drive download"
    try:
        raw = _request(endpoint, token=token)
    except HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HALT: {error_label} failed HTTP {e.code}: {detail}") from e
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise RuntimeError("HALT: Drive state content is not valid UTF-8 JSON text") from e


def normalize_state(state):
    if not isinstance(state, dict):
        raise RuntimeError("HALT: Drive state must be a JSON object")
    defaults = {
        "version": "1.1.1",
        "status": "INITIALIZED",
        "active_project": None,
        "execution_mode": "REAL",
        "task_lifecycle": {"NOW": None, "DEFERRED": [], "BLOCKED": [], "FUTURE": [], "REFERENCE": [], "COMPLETED": []},
        "authority_gate": {"pending_approval": None, "last_action": "INITIALIZATION"},
        "step": 0,
        "runner_engine": "GitHub Actions Autonomous Cloud Runner"
    }
    for key, value in defaults.items():
        if key not in state:
            state[key] = value
        elif isinstance(value, dict) and isinstance(state[key], dict):
            for nested_key, nested_value in value.items():
                state[key].setdefault(nested_key, nested_value)
    state["version"] = "1.1.1"
    return state


def main():
    token = get_access_token()
    folder_id = os.environ.get("GDRIVE_FOLDER_ID", "").strip()
    if not folder_id:
        raise RuntimeError("HALT: GDRIVE_FOLDER_ID is empty")
    file_info = find_state_file(token, folder_id)
    if not file_info:
        raise RuntimeError("HALT: aipp_state.json not found in configured Drive folder")
    state = normalize_state(read_drive_state(token, file_info))
    candidates = discover_task_candidates(token, folder_id)
    state = reconcile_discovered_tasks(state, candidates)
    if state["task_lifecycle"].get("NOW") is None and not state["task_lifecycle"].get("FUTURE") and candidates:
        state["discovered_task_candidates"] = candidates
    Path(STATE_FILE).write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"DRIVE_STATE_LOADED file_id={file_info['id']} version={state.get('version')} status={state.get('status')} now={state['task_lifecycle'].get('NOW')} future={len(state['task_lifecycle'].get('FUTURE', []))}")


if __name__ == "__main__":
    main()

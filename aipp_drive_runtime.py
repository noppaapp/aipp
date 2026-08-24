import json
import os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError

DRIVE_API = "https://www.googleapis.com/drive/v3"
STATE_FILE = "aipp_state.json"
GOOGLE_DOC_MIME = "application/vnd.google-apps.document"


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
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise RuntimeError("HALT: Drive state content is not valid UTF-8 JSON text") from e


def main():
    token = get_access_token()
    folder_id = os.environ.get("GDRIVE_FOLDER_ID", "").strip()
    if not folder_id:
        raise RuntimeError("HALT: GDRIVE_FOLDER_ID is empty")
    file_info = find_state_file(token, folder_id)
    if not file_info:
        raise RuntimeError("HALT: aipp_state.json not found in configured Drive folder")
    state = read_drive_state(token, file_info)
    if not isinstance(state, dict) or state.get("version") != "1.1.1":
        raise RuntimeError("HALT: Drive state is not a valid AIPP v1.1.1 state")
    Path(STATE_FILE).write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"DRIVE_STATE_LOADED file_id={file_info['id']} version={state.get('version')}")


if __name__ == "__main__":
    main()

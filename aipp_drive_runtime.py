import base64
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

DRIVE_API = "https://www.googleapis.com/drive/v3"
STATE_FILE = "aipp_state.json"


def _request(url, method="GET", data=None, token=None, content_type=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if content_type:
        headers["Content-Type"] = content_type
    req = Request(url, data=data, headers=headers, method=method)
    with urlopen(req) as response:
        return response.read()


def get_access_token():
    credentials = json.loads(os.environ["GDRIVE_CREDENTIALS"])
    refresh_token = os.environ["GCP_REFRESH_TOKEN"]
    payload = (
        f"client_id={credentials['client_id']}&"
        f"client_secret={credentials['client_secret']}&"
        f"refresh_token={refresh_token}&grant_type=refresh_token"
    ).encode()
    raw = _request(
        "https://oauth2.googleapis.com/token",
        method="POST",
        data=payload,
        content_type="application/x-www-form-urlencoded",
    )
    return json.loads(raw)["access_token"]


def find_state_file(token, folder_id):
    query = (
        f"name='{STATE_FILE}' and '{folder_id}' in parents and trashed=false"
    )
    url = f"{DRIVE_API}/files?q={query}&fields=files(id,name,mimeType)"
    result = json.loads(_request(url, token=token))
    files = result.get("files", [])
    return files[0] if files else None


def read_drive_state(token, file_id):
    raw = _request(f"{DRIVE_API}/files/{file_id}?alt=media", token=token)
    return json.loads(raw)


def write_local_state(state):
    Path(STATE_FILE).write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main():
    token = get_access_token()
    folder_id = os.environ["GDRIVE_FOLDER_ID"]
    file_info = find_state_file(token, folder_id)
    if not file_info:
        raise RuntimeError("HALT: aipp_state.json not found in configured Drive folder")
    state = read_drive_state(token, file_info["id"])
    if not isinstance(state, dict) or state.get("version") != "1.1.1":
        raise RuntimeError("HALT: Drive state is not a valid AIPP v1.1.1 state")
    write_local_state(state)
    print(json.dumps({"status": "DRIVE_STATE_LOADED", "file_id": file_info["id"], "version": state.get("version")}, ensure_ascii=False))


if __name__ == "__main__":
    main()

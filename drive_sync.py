import json
import os
import urllib.parse
import urllib.request
from urllib.error import HTTPError

STATE_FILE = "aipp_state.json"


def fail(message):
    raise RuntimeError(message)


def load_oauth_credentials(raw):
    raw = raw.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        parts = raw.replace(";", " ").split()
        if len(parts) >= 2:
            return parts[0], parts[1]
        fail("GDRIVE_CREDENTIALS formatı geçersiz.")

    client_id = data.get("client_id") or data.get("installed", {}).get("client_id") or data.get("web", {}).get("client_id")
    client_secret = data.get("client_secret") or data.get("installed", {}).get("client_secret") or data.get("web", {}).get("client_secret")
    if not client_id or not client_secret:
        fail("GDRIVE_CREDENTIALS içinde client_id/client_secret bulunamadı.")
    return client_id, client_secret


def request_json(url, *, data=None, headers=None, method=None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        fail(f"Google API HTTP {exc.code}: {detail}")


def main():
    raw_creds = os.environ.get("GDRIVE_CREDENTIALS", "").strip()
    refresh_token = os.environ.get("GCP_REFRESH_TOKEN", "").strip()
    folder_id = os.environ.get("GDRIVE_FOLDER_ID", "").strip()

    if not raw_creds or not refresh_token or not folder_id:
        fail("GDRIVE_CREDENTIALS, GCP_REFRESH_TOKEN veya GDRIVE_FOLDER_ID eksik.")

    client_id, client_secret = load_oauth_credentials(raw_creds)
    token_body = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }).encode()
    _, token = request_json(
        "https://oauth2.googleapis.com/token",
        data=token_body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    access_token = token.get("access_token")
    if not access_token:
        fail("Google OAuth access token üretilemedi.")

    query = "name = 'aipp_state.json' and '%s' in parents and trashed = false" % folder_id
    search_url = "https://www.googleapis.com/drive/v3/files?" + urllib.parse.urlencode({"q": query})
    headers = {"Authorization": f"Bearer {access_token}"}
    _, result = request_json(search_url, headers=headers)
    files = result.get("files", [])

    with open(STATE_FILE, "rb") as handle:
        content = handle.read()

    boundary = "aipp_drive_sync_boundary"
    if files:
        file_id = files[0]["id"]
        upload_url = f"https://www.googleapis.com/upload/drive/v3/files/{file_id}?uploadType=multipart"
        method = "PATCH"
        metadata = {"name": STATE_FILE}
        action = "updated"
    else:
        upload_url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart"
        method = "POST"
        metadata = {"name": STATE_FILE, "parents": [folder_id]}
        action = "created"

    body = (
        f"--{boundary}\r\n"
        "Content-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{json.dumps(metadata)}\r\n"
        f"--{boundary}\r\n"
        "Content-Type: application/json\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()

    status, _ = request_json(
        upload_url,
        data=body,
        headers={
            **headers,
            "Content-Type": f"multipart/related; boundary={boundary}",
        },
        method=method,
    )
    print(f"Drive sync OK: {action} {STATE_FILE}; HTTP {status}")


if __name__ == "__main__":
    main()

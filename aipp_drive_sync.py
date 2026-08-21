import json
import os
import sys
import urllib.parse
import urllib.request
from urllib.error import HTTPError


def fail(message: str) -> None:
    print(f"HATA: {message}")
    raise SystemExit(1)


refresh_token = os.environ.get("GCP_REFRESH_TOKEN", "").strip()
folder_id = os.environ.get("GDRIVE_FOLDER_ID", "").strip()
raw_creds = os.environ.get("GDRIVE_CREDENTIALS", "").strip()

if not all((refresh_token, folder_id, raw_creds)):
    fail("GCP_REFRESH_TOKEN, GDRIVE_FOLDER_ID veya GDRIVE_CREDENTIALS eksik.")

try:
    creds = json.loads(raw_creds)
except json.JSONDecodeError as exc:
    fail(f"GDRIVE_CREDENTIALS geçerli JSON değil: {exc}")

client_id = (
    creds.get("client_id")
    or creds.get("installed", {}).get("client_id")
    or creds.get("web", {}).get("client_id")
)
client_secret = (
    creds.get("client_secret")
    or creds.get("installed", {}).get("client_secret")
    or creds.get("web", {}).get("client_secret")
)

if not client_id or not client_secret:
    fail("GDRIVE_CREDENTIALS içinde client_id/client_secret bulunamadı.")

local_file_path = "aipp_state.json"
if not os.path.isfile(local_file_path):
    fail("aipp_state.json workspace içinde bulunamadı.")

# Exchange the stored refresh token for a short-lived access token.
data = urllib.parse.urlencode(
    {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
).encode("utf-8")

request = urllib.request.Request(
    "https://oauth2.googleapis.com/token",
    data=data,
    headers={"Content-Type": "application/x-www-form-urlencoded"},
)

try:
    with urllib.request.urlopen(request) as response:
        token_payload = json.loads(response.read().decode("utf-8"))
    access_token = token_payload["access_token"]
except HTTPError as exc:
    detail = exc.read().decode("utf-8", errors="replace")
    fail(f"Google OAuth HTTP {exc.code}: {detail}")
except (KeyError, json.JSONDecodeError) as exc:
    fail(f"Google OAuth yanıtı geçersiz: {exc}")

headers = {"Authorization": f"Bearer {access_token}"}
file_name = "aipp_state.json"
query = f"name = '{file_name}' and '{folder_id}' in parents and trashed = false"
search_url = "https://www.googleapis.com/drive/v3/files?" + urllib.parse.urlencode(
    {"q": query, "fields": "files(id,name)"}
)

try:
    with urllib.request.urlopen(urllib.request.Request(search_url, headers=headers)) as response:
        files = json.loads(response.read().decode("utf-8")).get("files", [])
except HTTPError as exc:
    detail = exc.read().decode("utf-8", errors="replace")
    fail(f"Google Drive arama HTTP {exc.code}: {detail}")

with open(local_file_path, "rb") as handle:
    file_content = handle.read()

boundary = "aipp-drive-sync-boundary"
if files:
    file_id = files[0]["id"]
    upload_url = f"https://www.googleapis.com/upload/drive/v3/files/{file_id}?uploadType=multipart"
    method = "PATCH"
    metadata = {"name": file_name}
    action = f"güncelleme (ID: {file_id})"
else:
    upload_url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart"
    method = "POST"
    metadata = {"name": file_name, "parents": [folder_id]}
    action = "oluşturma"

body = (
    f"--{boundary}\r\n"
    "Content-Type: application/json; charset=UTF-8\r\n\r\n"
    f"{json.dumps(metadata)}\r\n"
    f"--{boundary}\r\n"
    "Content-Type: application/json\r\n\r\n"
).encode("utf-8") + file_content + f"\r\n--{boundary}--\r\n".encode("utf-8")

upload_request = urllib.request.Request(
    upload_url,
    data=body,
    headers={
        **headers,
        "Content-Type": f"multipart/related; boundary={boundary}",
    },
    method=method,
)

try:
    with urllib.request.urlopen(upload_request) as response:
        print(f"Google Drive senkronizasyonu başarıyla tamamlandı: {action}; HTTP {response.status}")
except HTTPError as exc:
    detail = exc.read().decode("utf-8", errors="replace")
    fail(f"Google Drive yükleme HTTP {exc.code}: {detail}")

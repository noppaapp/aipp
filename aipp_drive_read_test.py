import json
import os
import urllib.parse
import urllib.request

raw_creds = os.environ.get("GDRIVE_CREDENTIALS", "").strip()
refresh_token = os.environ.get("GCP_REFRESH_TOKEN", "").strip()
folder_id = os.environ.get("GDRIVE_FOLDER_ID", "").strip()
if not all((raw_creds, refresh_token, folder_id)):
    raise SystemExit("Drive credentials missing")
creds = json.loads(raw_creds)
client_id = creds.get("client_id") or creds.get("installed", {}).get("client_id") or creds.get("web", {}).get("client_id")
client_secret = creds.get("client_secret") or creds.get("installed", {}).get("client_secret") or creds.get("web", {}).get("client_secret")
data = urllib.parse.urlencode({"client_id": client_id, "client_secret": client_secret, "refresh_token": refresh_token, "grant_type": "refresh_token"}).encode()
req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
with urllib.request.urlopen(req) as r:
    access_token = json.loads(r.read().decode())["access_token"]
headers = {"Authorization": f"Bearer {access_token}"}
q = f"'{folder_id}' in parents and trashed = false"
url = "https://www.googleapis.com/drive/v3/files?" + urllib.parse.urlencode({"q": q, "fields": "files(id,name,mimeType,modifiedTime)", "pageSize": 100})
with urllib.request.urlopen(urllib.request.Request(url, headers=headers)) as r:
    files = json.loads(r.read().decode()).get("files", [])
if not files:
    raise SystemExit("Configured Drive folder is empty")
print(f"DRIVE READ SUCCESS: files={len(files)}")
for item in sorted(files, key=lambda x: x["name"].lower()):
    print(f"DRIVE_FILE: {item['name']} | {item['mimeType']} | {item['id']}")
state = next((f for f in files if f["name"] == "aipp_state.json"), None)
if not state:
    raise SystemExit("aipp_state.json not found in configured Drive folder")
content_url = f"https://www.googleapis.com/drive/v3/files/{state['id']}?alt=media"
with urllib.request.urlopen(urllib.request.Request(content_url, headers=headers)) as r:
    payload = r.read().decode("utf-8")
json.loads(payload)
print(f"DRIVE STATE READ SUCCESS: file_id={state['id']}; bytes={len(payload.encode('utf-8'))}; valid_json=true")

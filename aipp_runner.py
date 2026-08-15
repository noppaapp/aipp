import os
import sys
import json
import argparse
import io
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# Google Drive API yetkileri
SCOPES = ['https://www.googleapis.com/auth/drive']

def get_drive_service():
    creds_path = "service_account.json"
    if not os.path.exists(creds_path):
        print(f"[!] HATA: {creds_path} bulunamadı.")
        sys.exit(1)
    creds = service_account.Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

def upload_or_update_file(service, folder_id, file_name, file_content, mime_type="application/json"):
    # Klasör içinde dosyayı ara
    query = f"trashed = false and name = '{file_name}' and '{folder_id}' in parents"
    response = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
    files = response.get('files', [])

    media = MediaIoBaseUpload(io.BytesIO(file_content.encode('utf-8')), mimetype=mime_type, resumable=True)

    if files:
        file_id = files[0]['id']
        service.files().update(
            fileId=file_id,
            media_body=media
        ).execute()
        print(f"[*] Guncellendi: {file_name} (ID: {file_id})")
    else:
        file_metadata = {'name': file_name, 'parents': [folder_id]}
        file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        print(f"[*] Olusturuldu: {file_name} (ID: {file.get('id')})")

def main():
    parser = argparse.ArgumentParser(description="AIPP Autonomous Runner")
    parser.add_argument("command", nargs="?", default="BAŞLA")
    parser.add_argument("--workspace", default=".")
    args = parser.parse_args()

    folder_id = os.environ.get("GDRIVE_FOLDER_ID")
    if not folder_id:
        print("[!] HATA: GDRIVE_FOLDER_ID eksik!")
        sys.exit(1)

    service = get_drive_service()

    # Durum yönetimi (State)
    state = {"status": "PROPOSAL_READY", "runner": "GitHub Actions", "step": 1}
    state_json = json.dumps(state, indent=2, ensure_ascii=False)
    
    upload_or_update_file(service, folder_id, "aipp_state.json", state_json, "application/json")
    upload_or_update_file(service, folder_id, "baglanti_testi.txt", "Baglanti basarili.", "text/plain")

    print("[*] Islem tamamlandi: Dosyalar Drive'a yazildi.")

if __name__ == "__main__":
    main()

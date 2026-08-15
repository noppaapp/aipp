import os
import sys
import json
import argparse
import io
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# BU SATIRI DEĞİŞTİRDİK (Artık tüm dosyaları görebilir)
SCOPES = ['https://www.googleapis.com/auth/drive']

def get_drive_service():
    creds_path = 'service_account.json'
    if not os.path.exists(creds_path):
        raise FileNotFoundError(f"Kimlik dosyası bulunamadı: {creds_path}")
    creds = service_account.Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

def upload_or_update_file(service, folder_id, filename, content, mimetype):
    if isinstance(content, str):
        media_content = io.BytesIO(content.encode('utf-8'))
    else:
        media_content = io.BytesIO(content)

    media = MediaIoBaseUpload(media_content, mimetype=mimetype, resumable=True)
    
    # Artık 'drive' yetkisiyle dosyayı bulabileceğiz
    query = f"name = '{filename}' and '{folder_id}' in parents and trashed = false"
    results = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
    files = results.get('files', [])

    if files:
        file_id = files[0]['id']
        file = service.files().update(
            fileId=file_id,
            media_body=media
        ).execute()
        print(f"Mevcut dosya başarıyla güncellendi! Drive Dosya ID: {file.get('id')}")
    else:
        # Eğer hala bulamıyorsa (dosya yoksa), hata ver ki kota hatasıyla uğraşmayalım
        raise FileNotFoundError(f"'{filename}' bulunamadı. Lütfen klasör içinde olduğundan emin ol.")

def main():
    parser = argparse.ArgumentParser(description="AIPP Runner")
    parser.add_argument("command", nargs="?", default="BAŞLA")
    parser.add_argument("--workspace", default=".")
    args = parser.parse_args()

    # Ortam değişkeninden klasör ID'sini al
    folder_id = os.environ.get("GDRIVE_FOLDER_ID")
    if not folder_id:
        raise ValueError("GDRIVE_FOLDER_ID bulunamadı!")

    service = get_drive_service()

    state_data = {
        "status": "RUNNING",
        "command": args.command,
        "workspace": args.workspace
    }
    state_json = json.dumps(state_data, indent=2)

    upload_or_update_file(service, folder_id, "aipp_state.json", state_json, "application/json")

if __name__ == "__main__":
    main()

import os
import sys
import json
import argparse
import io
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

SCOPES = ['https://www.googleapis.com/auth/drive']

def get_drive_service():
    creds_path = "service_account.json"
    if not os.path.exists(creds_path):
        print(f"[!] HATA: {creds_path} bulunamadı.")
        sys.exit(1)
    creds = service_account.Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

def upload_or_update_file(service, folder_id, file_name, file_content, mime_type="application/json"):
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
        print(f"[*] Google Drive dosyasi guncellendi: {file_name} (ID: {file_id})")
    else:
        file_metadata = {
            'name': file_name,
            'parents': [folder_id]
        }
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id'
        ).execute()
        print(f"[*] Google Drive dosyasi olusturuldu: {file_name} (ID: {file.get('id')})")

def main():
    parser = argparse.ArgumentParser(description="AIPP Autonomous Runner with Google Drive")
    parser.add_argument("command", nargs="?", default="BAŞLA", help="Command to execute")
    parser.add_argument("--workspace", default=".", help="Workspace directory")
    args = parser.parse_args()

    print(f"[*] AIPP Google Drive Runner baslatildi. Komut: {args.command}")

    folder_id = os.environ.get("GDRIVE_FOLDER_ID")
    if not folder_id:
        print("[!] HATA: GDRIVE_FOLDER_ID çevre değişkeni tanımlanmamış!")
        sys.exit(1)

    service = get_drive_service()

    # State verisini belirle veya oku
    state_file_name = "aipp_state.json"
    # Drive'dan mevcut state'i okumaya çalışabiliriz veya sıfırdan başlatabiliriz
    state = {"status": "INITIALIZED", "step": 1, "runner_engine": "Google Drive Cloud Runner"}
    state["step"] = state.get("step", 0) + 1
    state["status"] = "PROPOSAL_READY"

    state_json_str = json.dumps(state, indent=2, ensure_ascii=False)
    upload_or_update_file(service, folder_id, state_file_name, state_json_str, "application/json")

    # Bağlantı testi dosyası
    test_file_name = "baglanti_testi.txt"
    test_content = "AIPP Google Drive baglantisi basarili ve paylasilan klasöre yazildi."
    upload_or_update_file(service, folder_id, test_file_name, test_content, "text/plain")

    print(f"[*] Tum islemler Google Drive klasorune (ID: {folder_id}) basariyla yazildi.")

if __name__ == "__main__":
    main()

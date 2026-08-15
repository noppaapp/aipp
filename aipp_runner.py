import os
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

def upload_to_gdrive(file_path, folder_id):
    creds_path = "credentials.json"
    scopes = ['https://www.googleapis.com/auth/drive.file']
    
    creds = service_account.Credentials.from_service_account_file(creds_path, scopes=scopes)
    service = build('drive', 'v3', credentials=creds)

    file_metadata = {
        'name': os.path.basename(file_path),
        'parents': [folder_id]
    }
    media = MediaFileUpload(file_path, resumable=True)
    file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    print(f"[*] Dosya başarıyla yüklendi. Drive File ID: {file.get('id')}")

def main():
    workspace_dir = os.getcwd()
    state_path = os.path.join(workspace_dir, "aipp_state.json")
    
    if os.path.exists(state_path):
        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
        print(f"[*] Mevcut state yüklendi: {state}")
    else:
        state = {"status": "INITIALIZED", "step": 0}
        print(f"[*] Yeni state başlatıldı: {state}")

    # Protokol adımını ilerlet ve state'i guncelle
    state["step"] = state.get("step", 0) + 1
    state["status"] = "PROPOSAL_READY"
    state["runner_engine"] = "GitHub Actions Autonomous Cloud Runner"

    # State dosyasini kaydet
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

    print(f"[*] State basariyla guncellendi: {state}")
    print(f"[*] AIPP calismasi basariyla tamamlandi.")

    # Test dosyasi olusturarak Drive baglantisini dogrulama
    test_dosya_yolu = os.path.join(workspace_dir, "baglanti_testi.txt")
    with open(test_dosya_yolu, "w", encoding="utf-8") as f:
        f.write("AIPP baglantisi basarili.")
    print(f"[*] Baglanti testi dosyasi olusturuldu.")

    # Google Drive adaptör kontrolü ve yükleme
    adapter = os.getenv("AIPP_ADAPTER")
    folder_id = os.getenv("AIPP_GDRIVE_FOLDER")
    if adapter == "gdrive" and folder_id:
        try:
            upload_to_gdrive(test_dosya_yolu, folder_id)
        except Exception as e:
            print(f"[*] Google Drive yükleme hatası: {e}")
    else:
        print("[*] Yerel modda çalıştırıldı veya gdrive değişkenleri eksik.")

if __name__ == "__main__":
    main()
    

import os
import sys
import json
import argparse

def main():
    parser = argparse.ArgumentParser(description="AIPP Autonomous Runner")
    parser.add_argument("command", nargs="?", default="BAŞLA", help="Command to execute")
    parser.add_argument("--workspace", default=".", help="Workspace directory")
    args = parser.parse_args()

    print(f"[*] AIPP Runner baslatildi. Komut: {args.command}, Calisma alani: {args.workspace}")

    workspace_dir = args.workspace
    state_path = os.path.join(workspace_dir, "workspace_state.json")
    
    # Mevcut state dosyasini oku veya olustur
    if os.path.exists(state_path):
        with open(state_path, "r", encoding="utf-8") as f:
            try:
                state = json.load(f)
            except Exception:
                state = {"status": "INITIALIZED", "step": 0}
    else:
        state = {"status": "INITIALIZED", "step": 0}

    print(f"[*] Mevcut state yuklendi: {state}")

    # Protokol adimini ilerlet ve state'i guncelle
    state["step"] = state.get("step", 0) + 1
    state["status"] = "PROPOSAL_READY"
    state["runner_engine"] = "GitHub Actions Autonomous Cloud Runner"

    # State dosyasini kaydet
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

    print(f"[*] State basariyla guncellendi: {state}")
    print("[*] AIPP calismasi basariyla tamamlandi.")

if __name__ == "__main__":
    main()# Test dosyasi olusturarak Drive baglantisini dogrulama
    test_dosya_yolu = os.path.join(workspace_dir, "baglanti_testi.txt")
    with open(test_dosya_yolu, "w", encoding="utf-8") as f:
        f.write("AIPP baglantisi basarili.")
    print("[*] Baglanti testi dosyasi olusturuldu.")

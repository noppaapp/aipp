AIPP — KURULUM VE İLK ÇALIŞTIRMA
=================================

ÖNEMLİ: Bu depo tek dosyalı bir program değildir.
Güncel aipp_runner.py, başka Python dosyalarını ve runtime/ klasöründeki
bileşenleri kullanır. Yalnızca aipp_runner.py dosyasını indirip çalıştırmayın.
Aşağıdaki adımlar, GitHub deposunun tamamını kullanmak içindir.

1. GEREKLİLER
-------------
- Python 3.12 veya uyumlu bir Python 3 sürümü
- Git (depo klonlamak için) ya da GitHub'dan indirilen tam kaynak ZIP'i

2. DOSYALARI EDİNİN
-------------------
Önerilen yöntem: Depoyu bilgisayarınıza klonlayın:

    git clone https://github.com/noppaapp/aipp.git
    cd aipp

Git kurulu değilse https://github.com/noppaapp/aipp adresini açın,
Code > Download ZIP seçeneğiyle deponun TAMAMINI indirin ve ZIP'i açın.
Komutları, aipp_runner.py dosyasının bulunduğu aipp klasörünün içinde çalıştırın.

Sadece aipp_runner.py dosyasını kopyalamak yeterli değildir. Çalışma için
en azından aşağıdaki dosya ve klasörler depo içindeki yerlerinde bulunmalıdır:
- aipp_runner.py
- aipp_project_bootstrap.py
- aipp_authority.py
- aipp_drive_runtime.py
- runtime/continuation.py
- runtime/github_external.py
- runtime/github_target.py
- AIPP.md
- PROJECT_BOOT.md

Diğer depo dosyaları ve klasörleri de kaybolmadan birlikte tutulmalıdır.

3. GEREKLİ PAKETLERİ KURUN
--------------------------
Windows'ta PowerShell veya Komut İstemi'ni, macOS/Linux'ta Terminal'i açın.
Önce aipp klasörüne geçtiğinizden emin olun, sonra çalıştırın:

    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt pytest

Bazı bilgisayarlarda Python komutu 'python' yerine 'py' olabilir.
Windows'ta gerekirse komutları 'py -3.12' ile başlatın.

4. OTOMATİK TESTLER
-------------------
Aşağıdaki komut, depodaki testleri çalıştırır:

    python -m pytest -q

Testler başarısız olursa hata mesajını incelemeden kurulumu başarılı saymayın.

5. AIPP'Yİ BAŞLATIN
-------------------
AIPP çalışma alanında AIPP.md ve PROJECT_BOOT.md dosyaları bulunmalıdır.
Başlatmak için:

    python aipp_runner.py BAŞLA

Başka bir çalışma klasörünü açıkça belirtmek isterseniz:

    python aipp_runner.py BAŞLA --workspace "C:\AIPP\proje"

Komutun ürettiği durum bilgisini ve hata mesajlarını kontrol edin. Başlatma
komutunun çalışması tek başına bütün görevlerin tamamlandığı anlamına gelmez.
AIPP insan onayı gereken işlemlerde durur; bu onayı otomatik olarak vermez.

6. GOOGLE DRIVE HAKKINDA
------------------------
İlk yerel denemede Google Drive bağlantısını kurduğunuzu varsaymayın.
Drive kullanımı için gerekli kimlik doğrulama ve ayarlar ayrıca yapılandırılmalı;
kimlik bilgilerinizi veya erişim anahtarlarınızı kaynak koduna eklemeyin.

7. SORUN GİDERME
----------------
- "ModuleNotFoundError" görürseniz yalnızca runner dosyasını değil, deponun
  tamamını indirdiğinizi ve runtime/ klasörünün bulunduğunu kontrol edin.
- "AIPP.md" veya "PROJECT_BOOT.md" bulunamadı hatasında çalışma klasörünü kontrol edin.
- Testler başarısızsa hata çıktısını saklayın; başarısız testleri görmezden gelmeyin.

Bu belge, güncel GitHub deposundaki modüler çalışma yapısını anlatır.
Eski altı dosyalı runtime düzeni güncel kurulum yöntemi olarak kullanılmamalıdır.

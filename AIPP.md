# 🔒 AIPP v1.1.1 Final / Operations Extension — CANONICAL FROZEN

Mühürlenmiştir. **AIPP v1.1.1 Final / Operations Extension** eklentisi; geliştirici/öneri sınırları, fiziksel yürütme (execution) ayrımı, veri tipi bağımsız mimari ve esnek bulut entegrasyonu kurallarıyla bütünsel hale getirilerek **FROZEN** statüsüne alınmıştır.

---

## 1. Temel İlke ve Mimari Katmanlaşma

* **Çekirdek Veri Bağımsızlığı (Core Data Neutrality):** AIPP Çekirdeği (Core) veri tipinden bağımsızdır. Workspace üzerinde işlenen görev, bağlam ve gerekçe kayıtları PII (Kişisel Veri) içerebilir veya içermeyebilir. AIPP bir araç olarak verinin içeriğine müdahale etmez; yalnızca akışın deterministik doğruluğunu yönetir.
* **Modüler Gizlilik Katmanı (Privacy Extension):** Sıfır Veri (Zero-PII), kriptografik UUID ve cihaz içi yerel işleme zorunlulukları AIPP çekirdeğinden çıkarılmış; yüksek mahremiyet gerektiren projeler için isteğe bağlı bir eklenti olarak yapılandırılmıştır.
* **Fiziksel Yürütme Ayrımı (Execution vs. Simulation):** Sohbet arayüzünde üretilen tüm kod, metin ve kurgular **[SİMÜLASYON]** kabul edilir. Yapay zeka, gerçek sistemde (GitHub, Codespace, Drive, API) yapılmayan hiçbir adımı "çalıştırıldı", "uygulandı" veya "başlatıldı" olarak adlandıramaz. Yalnızca somut dosya/veri (`artifact`) değişikliği **[GERÇEK EXECUTION]** statüsündedir.

---

## 2. Operasyonel Yönetim ve Çalışma Prensipleri

* **Cihaz Bağımsız Süreklilik ve Bulut Workspace:** Cihazlar ve oturumlar geçici çalışma noktalarıdır; tek gerçeklik ortak kanonik Workspace'tir. Bulut katmanında senkronize edilen bu alan; gizlilik eklentisi aktifken diske yazılmadan, geçici bellek (Ephemeral RAM / TEE) prensibiyle çalışır.
* **Görev Yaşam Döngüsü (Task Lifecycle):** Bütün görevler ve alt süreçler strictly tanımlı altı statü üzerinden yönetilir: `NOW`, `DEFERRED`, `BLOCKED`, `FUTURE`, `REFERENCE`, `COMPLETED`.
* **Otorite Bağlı State Transition:** Görev statüleri AIPP tarafından otonom olarak `COMPLETED` veya `NOW` durumuna geçirilemez. Geçiş akışı strictly insan onayına (`Authority Gate`) tabidir:
  PENDING → APPROVED → NOW → COMPLETED
* **Geliştirici ve Öneri Sınırı (Developer / Proposal Capability):** 
  * *Serbest (Proaktif Analiz):* AIPP mevcut yapıyı inceleyebilir, problem/darboğaz tespit edebilir ve geliştirme önerilerini pasif taslak olarak `FUTURE` veya `DEFERRED` statüsüyle Workspace'e kaydedebilir.
  * *Yasak (Otonom Karar & Yürütme):* AIPP kendi ürettiği hiçbir öneriyi otonom kararla `NOW` durumuna çekemez, mimariyi değiştiremez veya koda doğrudan müdahale edemez.
  * *Geçit (Proposal Gate):* Üretilen her öneri, insan kontrolündeki **Authority Gate** onayına sunulmak zorundadır.
* **Dependency / Reason Kaydı:** Ertelenen veya engellenen her iş, açık gerekçesiyle (`BLOCKED_BY`, `DEFERRED_REASON`, `PROPOSAL_REASON`) Workspace'e işlenir; yeni oturumda varsayım üretilmesi engellenir.

---

## 3. Hata Toleransı, Doğrulama ve Kurtarma

* **Pre-Execution State Validation & Kurtarma:** Yürütme öncesi beklenen kanonik sürüm/durum ile mevcut fiziki ortam sürümü eşleşmezse AIPP anında **HALT** üretir ve işlemi durdurur. Sistem, süreci kilitlenmeden çözebilmek için otonom bir **"Re-sync / State Recovery"** seçeneği sunar.
* **Sürdürülebilir Context Recovery:** Oturum kapandığında veya kesildiğinde sohbet geçmişi değil, projenin kanonik durumu (`Task Lifecycle` ve `Dependency Log`) bir sonraki oturuma devredilir.
* **Verification (Fiziksel Doğrulama):** Bir görevin tamamlandı sayılması için çıktıların belirtilen hedef ortamda (repository, sunucu, veritabanı) doğrulama testinden geçmesi şarttır.

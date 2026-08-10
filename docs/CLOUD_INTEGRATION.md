# AIPP Cloud Integration & Service Boundaries

**STATUS:** DRAFT / PROPOSED  
**SECURITY MODEL:** Zero-PII / Privacy-by-Design  

---

## 1. TEMEL İLKELER
* **Zero PII Storage:** Sunucu altyapısında hiçbir kişisel veri (PII) saklanmaz.
* **Kriptografik Kimlik:** Kullanıcı ve cihaz kimlikleri yalnızca anonim UUID ve cihaz tabanlı anahtarlarla yönetilir.
* **Stateless Relay:** Bulut servisleri yalnızca durum iletimi ve anonim doğrulama katmanı olarak çalışır.

## 2. SERVİS SINIRLARI
* **Veritabanı / Depolama:** Sunucu tarafında veri tutulmaz, veriler cihaz üzerinde yerel (local storage/bulk) depolanır.
* **API Geçitleri:** Anonimleştirilmiş yetkilendirme mimarisi kullanılır.

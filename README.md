# ScrapeHub — Kurumsal (Enterprise) Web Scraping Pipeline

[![CI](https://github.com/7mertyavuz/websc/actions/workflows/ci.yml/badge.svg)](https://github.com/7mertyavuz/websc/actions/workflows/ci.yml)

Mikroservis mantığıyla çalışan, yatayda ölçeklenebilir, WAF (Datadome/Cloudflare) korumalarını aşabilen ve proxy maliyetlerini optimize eden gelişmiş bir web scraping mimarisidir. 

Eğitim amaçlı `books.toscrape.com` üzerinde kurgulanmış olsa da, altyapısı gerçek dünyadaki en zorlu sitelerden her gün yüz binlerce ilan/ürün çekmek için **Kurumsal (Enterprise)** standartlarda tasarlanmıştır.

> 📖 **Mimariyi derinlemesine anlamak için → [DOKUMANTASYON.md](DOKUMANTASYON.md)**

---

## 🚀 Sürüm Güncellemesi: Neler Değişti? (Eski Sürüme Göre)

Bu sürümde, sistemi "lokal test" ortamından "canlı (production)" ortamına taşımak için devasa mimari değişiklikler yapılmıştır:

1. **🔒 X-API-Key Güvenliği:** Eskiden dış dünyaya açık olan `/scrape` endpoint'leri artık `X-API-Key` başlığı ile korunmaktadır. Kötü niyetli kişilerin proxy bütçenizi tüketmesi engellendi.
2. **🛡️ Stealth & WAF Bypass (curl_cffi):** Standart `httpx` kütüphanesi kaldırıldı. Yerine, güvenlik duvarlarını (Datadome/Cloudflare) aşmak için gerçek Google Chrome TLS parmak izini (JA3) taklit eden `curl_cffi` entegre edildi. Sistem artık bir bot değil, "Chrome 120" olarak görünüyor.
3. **🌊 Proxy Şelalesi (Waterfall):** Tek proxy kullanmak yerine "Şelale" mantığı getirildi. Sistem önce bedava IP'yi dener; banlanırsa Ucuz Proxy'e (Tier 1), o da banlanırsa Pahalı Mobil Proxy'e (Tier 2) geçer. Bütçe %80 oranında optimize edildi.
4. **⚡ Worker-Safe Veritabanı (Race Condition Fix):** Eskiden iki Celery worker'ı aynı anda aynı URL'yi yazmaya çalıştığında sistem çöküyordu (Race Condition). Artık doğrudan **PostgreSQL `ON CONFLICT`** native özelliği kullanılarak, saniyede binlerce isteğe dayanıklı kusursuz Upsert (Güncelle/Ekle) yapısı kuruldu. (SQLite desteği performans için tamamen bırakıldı).
5. **🎯 Force (Zorla) Parametresi:** Bloom Filter (Tekilleştirme) bir URL'yi gördüğünde bir daha çekmiyordu. Artık API'den `force=True` göndererek istediğiniz ilanı zorla güncelletebilirsiniz.

---

## Mimari (5 Katmanlı)

```text
  ┌──────────────┐   POST /scrape    ┌──────────────────┐
  │   İstemci /   │ ───────────────► │  FastAPI (API)   │   Katman 1: Orkestratör
  │   Cron job    │  (X-API-Key)     │   app/main.py    │
  └──────────────┘                  └────────┬─────────┘
                                              │ .delay()
                                     ┌────────▼─────────┐
                                     │  Redis (broker)  │   Katman 1: Kuyruk
                                     └────────┬─────────┘
                                              │
                              ┌───────────────▼───────────────┐
                              │   Celery Workers (xN)         │
                              │   workers/tasks.py            │
                              │                               │
                              │  1. Dedup  (Bloom Filter)     │◄─ Katman 2
                              │  2. Fetch  (Stealth + Proxy)  │◄─ Katman 3+4
                              │  3. Parse  (Çok Kademeli)     │◄─ Katman 5
                              │  4. Store  (ON CONFLICT)      │
                              └───────────────┬───────────────┘
                                              │
                                     ┌────────▼──────────┐
                                     │    PostgreSQL     │   Depolama
                                     └───────────────────┘

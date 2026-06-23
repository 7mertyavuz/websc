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
Hızlı Başlangıç (Docker ile Tam Dağıtık Mod)
Sistem artık native PostgreSQL gücü kullandığı için docker-compose ile çalıştırılması zorunludur.

Bash
docker compose up --build
Servisler ayağa kalktıktan sonra:

API: http://localhost:8000

Flower (Görev İzleme): http://localhost:5555

Prometheus Metrikleri: http://localhost:8000/metrics

Yeni API anahtarı korumasıyla bir kazıma işi başlatmak için:

Bash
curl -X POST localhost:8000/scrape \
     -H "Content-Type: application/json" \
     -H "X-API-Key: BENIM_GIZLI_SIFREM_123" \
     -d '{"max_pages": 5, "chunk_size": 10}'
(Not: BENIM_GIZLI_SIFREM_123 değerini kendi .env dosyanıza göre değiştirin).

API Uç Noktaları
Tüm POST ve GET istekleri yetkilendirme veya izleme odaklıdır. POST isteklerinde header olarak X-API-Key zorunludur.

Uç Nokta	Metot	Açıklama
/scrape	POST	Katalog tarama işini kuyruğa atar. X-API-Key zorunludur.
/scrape-one	POST	Tek bir URL'i kazır. force=true verilirse Bloom Filter'ı atlar.
/status/{task_id}	GET	Celery görev durumunu canlı sorgular.
/stats	GET	DB'deki kayıt sayısı + dedup backend durumu.
/health	GET	Derin Health-Check: Redis ve PostgreSQL'e ping atıp 200 veya 503 döner.
/metrics	GET	Prometheus metrikleri (Başarılı çekim, hata oranları, dead-letter kuyruğu).
Konfigürasyon ve Proxy Ayarları (.env)
Aşağıdaki değişkenleri sunucunuzdaki .env dosyasına veya docker-compose.yml içine ekleyebilirsiniz.

Değişken	Default	Açıklama
API_KEY	BENIM_GIZLI_SIFREM_123	FastAPI endpoints koruma şifresi.
PROXY_TIER_1	(boş)	Şelale Aşama 1: Datacenter veya Scrapoxy URL'i (Örn: http://localhost:8888)
PROXY_TIER_2	(boş)	Şelale Aşama 2: Korumalı siteler için Residential / Mobil IP adresi.
SCRAPE_BASE_URL	books.toscrape.com	Hedef site adresi.
MAX_CONCURRENCY	4	Worker başına saniyede işlenecek görev limiti.
INCREMENTAL	false	true ise Bloom filter atlanır, içerik değişimine (hash) bakılır.
LOG_LEVEL	INFO	Log detay seviyesi (DEBUG, INFO, ERROR).
Etik & Yasal UYARI
Bu proje, izin veren hedeflerde (books.toscrape.com) doğru mühendisliği (kuyruk yönetimi, proxy şelalesi, stealth bypass) öğretmek içindir. Altyapı dünyanın en katı WAF'larını aşabilecek güce sahip olsa da, kullanım şartlarını (TOS) ihlal eden hedeflere yönelik izinsiz scraping eylemlerinin hukuki sorumluluğu tamamen kullanıcıya aittir.

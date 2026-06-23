# ScrapeHub — Dağıtık Web Scraping Pipeline (Eğitim Projesi)

Mikroservis mantığıyla çalışan, ölçeklenebilir bir web scraping mimarisi.
Hedef site: **books.toscrape.com** — scraping pratiği için açıkça yayınlanmış,
anti-bot savunması olmayan, kullanımına izin verilen demo sitesi.

Bu proje bir **mühendislik mimarisini** öğretmek için yazıldı: asenkron kuyruk,
worker dağıtımı, tekilleştirme (deduplication), retry/backoff ve şemaya dayalı
parsing. Aynı iskelet, izin veren herhangi bir site veya açık API için kullanılabilir.

## Mimari (5 katman)

```
  ┌──────────────┐   POST /scrape    ┌──────────────────┐
  │   İstemci /   │ ───────────────► │  FastAPI (API)   │   Katman 1: Orkestratör
  │   Cron job    │                  │   app/main.py    │
  └──────────────┘                  └────────┬─────────┘
                                              │ .delay()
                                     ┌────────▼─────────┐
                                     │  Redis (broker)  │   Katman 1: Kuyruk
                                     └────────┬─────────┘
                                              │
                              ┌───────────────▼───────────────┐
                              │   Celery Workers (xN)          │
                              │   workers/tasks.py             │
                              │                                │
                              │  1. Dedup  (Bloom filter) ─────┼─► Katman 2
                              │  2. Fetch  (httpx+retry)  ─────┼─► Katman 3+4
                              │  3. Parse  (CSS / LLM)    ─────┼─► Katman 5
                              │  4. Store                      │
                              └───────────────┬────────────────┘
                                              │
                                     ┌────────▼─────────┐
                                     │ PostgreSQL/SQLite │   Depolama
                                     └──────────────────┘
```

| Katman | Görev | Dosya | Araç |
|--------|-------|-------|------|
| 1 | API + Kuyruk | `app/main.py`, `workers/celery_app.py` | FastAPI, Celery, Redis |
| 2 | Tekilleştirme | `core/dedup.py` | RedisBloom (fallback: in-memory) |
| 3+4 | Nazik indirme | `core/fetcher.py` | httpx + retry/backoff + robots.txt |
| 5 | Ayrıştırma | `parser/extract.py` | BeautifulSoup + Pydantic (opsiyonel LLM) |
| - | Depolama | `storage/db.py` | SQLAlchemy → Postgres/SQLite |

## Hızlı başlangıç (Redis/Celery KURMADAN)

Önce çalıştığını gör:

```bash
pip install -r requirements.txt
python run_local.py --pages 2
```

Bu, tüm pipeline'ı senkron çalıştırır: dedup → fetch → parse → SQLite'a yazar.
Sıfır altyapı gerekir.

## Tam dağıtık mod (Docker)

```bash
docker compose up --build
```

Sonra:

```bash
# kazıma işi başlat
curl -X POST localhost:8000/scrape -H "Content-Type: application/json" \
     -d '{"max_pages": 5}'

# durum
curl localhost:8000/stats
```

## Manuel dağıtık mod (Docker olmadan)

```bash
# 1. Redis Stack (Bloom filter dahil)
docker run -p 6379:6379 redis/redis-stack:latest

# 2. Worker (ayrı terminal)
celery -A workers.celery_app.celery_app worker --loglevel=info --concurrency=4

# 3. API (ayrı terminal)
uvicorn app.main:app --reload
```

## Konfigürasyon (env)

| Değişken | Default | Açıklama |
|----------|---------|----------|
| `SCRAPE_BASE_URL` | books.toscrape.com | hedef site |
| `REDIS_URL` | redis://localhost:6379/0 | kuyruk + bloom |
| `DATABASE_URL` | sqlite:///scrapehub.db | Postgres'e çevrilebilir |
| `REQUEST_DELAY` | 0.5 | istekler arası saniye (nezaket) |
| `MAX_CONCURRENCY` | 4 | eşzamanlı istek |
| `USE_LLM_PARSER` | false | true → LLM tabanlı parser |

## Tasarım notları

- **Neden Bloom filter?** 500k URL'i SQL'de tek tek aramak pahalı; Bloom filter
  RAM'de O(1) "görüldü mü?" cevabı verir (ayarlanabilir false-positive oranı).
- **Neden retry/backoff?** 429/503 alınca üstel artan beklemeyle sunucuya saygı.
- **Neden iki parser?** CSS parser hızlı/ücretsiz; LLM parser HTML değişse de
  şemaya sadık kalır (XPath kırılması derdini çözer).
- **Neden SQLite fallback?** Repoyu klonlayan kişi sıfır kurulumla çalıştırabilsin.

## Etik & yasal

- Hedef site (toscrape) scraping pratiği için **kasıtla** yayınlanmıştır.
- `core/fetcher.py` robots.txt'e saygı duyar ve nezaket gecikmesi uygular.
- Başka bir siteye yönlendirirken: kullanım şartlarını, robots.txt'i ve ilgili
  veri koruma mevzuatını (ör. KVKK/GDPR) kontrol et. Anti-bot savunması olan
  sitelerde izinsiz kullanma.

# ScrapeHub — Dağıtık Web Scraping Pipeline (Eğitim Projesi)

[![CI](https://github.com/7mertyavuz/websc/actions/workflows/ci.yml/badge.svg)](https://github.com/7mertyavuz/websc/actions/workflows/ci.yml)

Mikroservis mantığıyla çalışan, ölçeklenebilir bir web scraping mimarisi.
Hedef site: **books.toscrape.com** — scraping pratiği için açıkça yayınlanmış,
anti-bot savunması olmayan, kullanımına izin verilen demo sitesi.

Bu proje bir **mühendislik mimarisini** öğretmek için yazıldı: asenkron kuyruk,
worker dağıtımı, tekilleştirme (deduplication), retry/backoff ve şemaya dayalı
parsing. Aynı iskelet, izin veren herhangi bir site veya açık API için kullanılabilir.

> 📖 **Projeyi sıfırdan, derinlemesine anlamak için → [DOKUMANTASYON.md](DOKUMANTASYON.md)**
> (her katman, her dosya, veri akışı ve tasarım kararları bol açıklamayla anlatılır.)

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
                              │  3. Parse  (çok kademeli) ─────┼─► Katman 5
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
| 5 | Ayrıştırma | `parser/extract.py` | BeautifulSoup + Pydantic (LLM'siz, çok kademeli) |
| - | Depolama | `storage/db.py` | SQLAlchemy → Postgres/SQLite (`url` üzerinde unique index) |
| - | Loglama | `core/logging.py` | stdlib `logging` (env: `LOG_LEVEL`/`LOG_FILE`) |
| - | Metrikler | `core/metrics.py`, `/metrics` | Prometheus formatı (Redis-backed sayaçlar) |
| - | İzleme | `docker-compose.yml` (flower), `/health` | Celery Flower + derin health-check |
| - | CI | `.github/workflows/ci.yml` | GitHub Actions (push/PR → pytest) |

## Hızlı başlangıç (Redis/Celery KURMADAN)

Önce çalıştığını gör:

```bash
pip install -r requirements.txt
python run_local.py --pages 2
```

Bu, tüm pipeline'ı senkron çalıştırır: dedup → fetch → parse → SQLite'a yazar.
Sıfır altyapı gerekir.

## Test

```bash
pytest -q
```

`tests/` paketi parser (çok kademeli çıkarım), dedup (ilk görüş False / ikinci True),
DB upsert (duplicate satır yok), chunk dağıtımı, domain-bazlı gecikme, içerik-hash
incremental ve dead-letter mantığını kapsar. Postgres entegrasyon testi
(`tests/test_db_postgres.py`) Postgres erişilemezse otomatik **skip** edilir.

Canlı RedisBloom doğrulaması (bir Redis Stack ayaktayken):

```bash
REDIS_URL=redis://localhost:6379/0 python tests/verify_bloom.py
```

Canlı PostgreSQL doğrulaması (`storage/db.py`'ı gerçek Postgres'e karşı sınar):

```bash
docker compose up -d postgres
# pytest entegrasyon testi (Postgres yoksa skip):
POSTGRES_TEST_URL=postgresql+psycopg2://scrape:scrape@localhost:5432/scrapehub \
    pytest tests/test_db_postgres.py
# veya standalone script (yaz/oku PASS/FAIL raporu):
DATABASE_URL=postgresql+psycopg2://scrape:scrape@localhost:5432/scrapehub \
    python tests/verify_postgres.py
```

## Tam dağıtık mod (Docker)

```bash
docker compose up --build
```

Servisler: `redis` (broker + RedisBloom), `postgres`, `api` (FastAPI),
`worker` (Celery), `flower` (izleme arayüzü → http://localhost:5555).

Sonra:

```bash
# kazıma işi başlat (chunk_size ile gruplu dağıtım)
curl -X POST localhost:8000/scrape -H "Content-Type: application/json" \
     -d '{"max_pages": 5, "chunk_size": 10}'

# durum
curl localhost:8000/stats

# derin health-check (Redis + DB bağlantısı; biri fail ise HTTP 503)
curl localhost:8000/health

# Prometheus metrikleri
curl localhost:8000/metrics

# worker/görev izleme
open http://localhost:5555      # Flower
```

## Manuel dağıtık mod (Docker olmadan)

```bash
# 1. Redis Stack (Bloom filter dahil)
docker run -p 6379:6379 redis/redis-stack:latest

# 2. Worker (ayrı terminal)
celery -A workers.celery_app.celery_app worker --loglevel=info --concurrency=4

# 3. API (ayrı terminal)
uvicorn app.main:app --reload

# 4. (Opsiyonel) Flower izleme
celery -A workers.celery_app.celery_app flower --port=5555
```

## API uçları

| Uç | Metot | Açıklama |
|----|-------|----------|
| `/scrape` | POST | Katalog tarama işini kuyruğa atar (`start_url`, `max_pages`, `chunk_size`) |
| `/scrape-one` | POST | Tek bir URL'i kuyruğa atar |
| `/status/{task_id}` | GET | Celery görev durumu |
| `/stats` | GET | DB'deki kitap sayısı + dedup backend |
| `/health` | GET | **Derin health-check:** Redis + DB'ye gerçekten bağlanır; her birini `ok/fail` döndürür. Biri bile fail ise **HTTP 503**, hepsi ok ise 200 |
| `/metrics` | GET | **Prometheus** text exposition formatında metrikler |

## Gözlemlenebilirlik (logging · health · metrics)

- **Yapılandırılmış loglama** (`core/logging.py`): tüm modüller stdlib `logging`
  kullanır (`print` yok). Seviye `LOG_LEVEL` env'inden; `LOG_FILE` verilirse loglar
  konsola ek olarak dosyaya da yazılır.
- **Derin health-check** (`GET /health`): yalnızca "ayakta mı" değil, Redis'e `PING`
  ve DB'ye `SELECT 1` atarak gerçek bağlanabilirliği test eder; bağımlılıklardan biri
  düşükse HTTP 503 + ayrıntılı `checks` döndürür (load balancer/k8s readiness için).
- **Prometheus metrikleri** (`GET /metrics`): `scrapehub_pages_processed_total`,
  `scrapehub_failed_fetch_total` (counter), `scrapehub_dead_letter_depth`,
  `scrapehub_db_books` (gauge). Sayaçlar **Redis'te paylaşımlıdır** — API ve
  worker'lar ayrı process olduğundan aynı değeri görür (Redis yoksa in-memory fallback).

## Sürekli entegrasyon (CI)

Her push ve pull request'te [GitHub Actions](.github/workflows/ci.yml) Python 3.11/3.12
üzerinde bağımlılıkları kurar ve `pytest` çalıştırır (durum: üstteki **CI** rozeti).
Testler izole geçici SQLite + in-memory dedup fallback kullandığından CI'da Redis/Postgres
gerektirmez.

## Konfigürasyon (env)

| Değişken | Default | Açıklama |
|----------|---------|----------|
| `SCRAPE_BASE_URL` | books.toscrape.com | hedef site |
| `REDIS_URL` | redis://localhost:6379/0 | kuyruk + bloom |
| `DATABASE_URL` | sqlite:///scrapehub.db | Postgres'e çevrilebilir |
| `LOG_LEVEL` | INFO | log seviyesi (DEBUG/INFO/WARNING/ERROR) |
| `LOG_FILE` | (boş) | verilirse loglar konsola ek olarak bu dosyaya yazılır |
| `REQUEST_DELAY` | 0.5 | istekler arası saniye (genel default) |
| `DOMAIN_DELAYS` | (boş) | domain-bazlı gecikme, ör. `books.toscrape.com:0.5,example.com:2.0` |
| `MAX_CONCURRENCY` | 4 | eşzamanlı istek |
| `INCREMENTAL` | false | true → içerik değiştiyse yeniden işle (content-hash) |
| `CONTENT_HASH_TTL` | 604800 | incremental içerik hash'lerinin saklanma süresi (sn) |

İş başlatma parametreleri (`POST /scrape`): `start_url`, `max_pages`, `chunk_size`
(>1 ise URL'ler Celery `chunks` ile gruplanır; <=1 ise tek tek dağıtılır).

## Tasarım notları

- **Neden Bloom filter?** 500k URL'i SQL'de tek tek aramak pahalı; Bloom filter
  RAM'de O(1) "görüldü mü?" cevabı verir (ayarlanabilir false-positive oranı).
- **Neden retry/backoff + dead-letter?** 429/503 alınca üstel artan beklemeyle
  sunucuya saygı; kalıcı başarısızlar `scrapehub:dead_letter` listesine yazılır
  (operatör inceleyip yeniden işleyebilir).
- **Neden çok kademeli parser?** Tek bir CSS seçici kırılsa bile alan boş kalmasın:
  her alan sırayla **(1)** JSON-LD/`og:`+meta → **(2)** çoklu yedek CSS seçici →
  **(3)** regex dener. LLM/API anahtarı gerektirmez; site tasarımı değişse de çalışır.
- **Neden chunk dağıtımı?** Binlerce URL'i tek tek kuyruğa atmak broker'a binlerce
  mesaj demek; `chunks` ile gruplayınca daha az mesaj, daha iyi throughput.
- **Neden incremental?** Değişmeyen sayfaları içerik hash'iyle atlayıp yalnızca
  fiyat/stok gibi gerçekten değişen sayfaları yeniden işlemek için.
- **Neden SQLite fallback?** Repoyu klonlayan kişi sıfır kurulumla çalıştırabilsin.

## Etik & yasal

- Hedef site (toscrape) scraping pratiği için **kasıtla** yayınlanmıştır.
- `core/fetcher.py` robots.txt'e saygı duyar ve nezaket gecikmesi uygular.
- Başka bir siteye yönlendirirken: kullanım şartlarını, robots.txt'i ve ilgili
  veri koruma mevzuatını (ör. KVKK/GDPR) kontrol et. Anti-bot savunması olan
  sitelerde izinsiz kullanma.

# ScrapeHub — AI-Augmented Web Scraping Pipeline

[![CI](https://github.com/7mertyavuz/websc/actions/workflows/ci.yml/badge.svg)](https://github.com/7mertyavuz/websc/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**[English](#english) | [Türkçe](#türkçe)**

A production-ready, horizontally scalable web scraping pipeline built with **FastAPI**, **Celery**, **Redis**, **PostgreSQL**, and **OpenTelemetry**. It handles catalog crawling, duplicate filtering, resilient fetching, multi-stage parsing, and persistent storage — with an optional AI agentic mode powered by Playwright + Ollama.

> **Status:** This project uses `books.toscrape.com` as an educational target, but the architecture is designed for enterprise-grade scraping workloads.
> 
> 📖 **Deep dive into the architecture → [DOKUMANTASYON.md](DOKUMANTASYON.md)**
> 
> 📖 **Mimariyi derinlemesine incelemek için → [DOKUMANTASYON.md](DOKUMANTASYON.md)**

---

## English

### What is ScrapeHub?

ScrapeHub is a distributed web scraping pipeline that turns a website into structured data stored in a database. It is designed around five independent layers:

1. **Orchestrator** — FastAPI gateway that receives requests and queues work.
2. **Queue** — Redis-backed Celery broker for distributing tasks.
3. **Deduplication** — Bloom filter + content hash to avoid redundant work.
4. **Fetch & Parse** — `curl_cffi` for stealth, Playwright for JS-heavy pages, and a robust fallback parser.
5. **Storage** — SQLAlchemy + PostgreSQL/SQLite with atomic upserts.

### Highlights

- **Microservice-oriented:** API, workers, Redis, Postgres, and Flower each run as separate services.
- **Horizontal scaling:** Add more Celery workers to increase throughput.
- **Resilient fetching:** Retry with exponential backoff, jitter, and domain-based politeness delays.
- **Deduplication:** RedisBloom when available, in-memory fallback otherwise.
- **Incremental mode:** Re-fetch only when page content changes.
- **AI agentic mode:** Dynamic scraping via Browserless Chrome + Ollama LLM.
- **Dead-letter queue:** Failed tasks are captured for later inspection.
- **Observability:** Prometheus metrics, Flower task monitoring, and Jaeger distributed tracing.
- **Web dashboard:** Dark-themed control panel served at `http://localhost:8000`.

### Quick Start

#### Option A — Zero-infrastructure (local SQLite)

```bash
pip install -r requirements.txt
python run_local.py --pages 2
```

#### Option B — Full distributed mode (Docker)

```bash
docker compose up --build
```

Then start a scrape:

```bash
curl -X POST http://localhost:8000/scrape \
  -H "Content-Type: application/json" \
  -H "X-API-Key: BENIM_GIZLI_SIFREM_123" \
  -d '{"max_pages": 5, "chunk_size": 10}'
```

Check progress:

```bash
curl http://localhost:8000/stats
curl http://localhost:8000/health
```

Open the dashboard:

- **Web UI:** http://localhost:8000
- **Flower:** http://localhost:5555
- **Metrics:** http://localhost:8000/metrics
- **Jaeger:** http://localhost:16686

### API Endpoints

All `POST` endpoints require the `X-API-Key` header.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Web dashboard (`index.html`). |
| `/scrape` | POST | Queue catalog crawling (standard mode). |
| `/scrape-dynamic` | POST | Queue catalog crawling (AI / Playwright mode). |
| `/scrape-one` | POST | Scrape a single URL; `force=true` skips deduplication. |
| `/status/{task_id}` | GET | Celery task status. |
| `/stats` | GET | Book count + deduplication backend info. |
| `/books` | GET | Paginated books from the database. |
| `/dead-letter` | GET | Failed tasks captured for inspection. |
| `/health` | GET | Deep health check: Redis + PostgreSQL. |
| `/metrics` | GET | Prometheus metrics endpoint. |

### Configuration

Key environment variables (see `core/config.py` for the full list):

| Variable | Default | Description |
|----------|---------|-------------|
| `SCRAPE_BASE_URL` | `https://books.toscrape.com/` | Target site |
| `REDIS_URL` | `redis://localhost:6379/0` | Broker + Bloom filter |
| `DATABASE_URL` | `sqlite:///scrapehub.db` | PostgreSQL recommended for production |
| `API_KEY` | `BENIM_GIZLI_SIFREM_123` | FastAPI endpoint protection |
| `REQUEST_DELAY` | `0.5` | Politeness delay between requests |
| `MAX_CONCURRENCY` | `4` | Worker concurrency base |
| `MAX_RETRIES` | `3` | Retry attempts for failed fetches |
| `INCREMENTAL` | `false` | Only re-process when content changes |
| `BROWSERLESS_URL` | `ws://localhost:3000` | Headless Chrome for AI mode |
| `OLLAMA_URL` | `http://127.0.0.1:11434` | Local LLM endpoint |
| `JAEGER_ENDPOINT` | `http://localhost:4318/v1/traces` | OpenTelemetry traces |

### Testing

```bash
pytest -q
```

Tests are isolated by `tests/conftest.py` using a temporary SQLite database and in-memory deduplication.

### Ethical & Legal Notice

This project is intended for educational use on permissive targets. `core/fetcher.py` respects `robots.txt` and applies politeness delays. The user is fully responsible for complying with the target site's Terms of Service and applicable data privacy laws (GDPR/KVKK) when scraping other domains.

---

## Türkçe

### ScrapeHub Nedir?

ScrapeHub, bir web sitesini yapılandırılmış veriye dönüştüren ve veritabanına yazan dağıtık bir web scraping pipeline'ıdır. Beş bağımsız katman üzerine kuruludur:

1. **Orkestratör** — İstekleri alan ve işleri kuyruğa koyan FastAPI ağ geçidi.
2. **Kuyruk** — Redis destekli Celery broker'ı ile görev dağıtımı.
3. **Tekilleştirme** — Gereksiz işi önleyen Bloom filter + içerik hash'i.
4. **Fetch & Parse** — Stealth için `curl_cffi`, JS ağırlıklı sayfalar için Playwright ve dayanıklı fallback parser.
5. **Depolama** — Atomik upsert destekli SQLAlchemy + PostgreSQL/SQLite.

### Öne Çıkan Özellikler

- **Mikroservis odaklı:** API, worker'lar, Redis, Postgres ve Flower ayrı servisler olarak çalışır.
- **Yatay ölçeklenebilir:** Daha fazla Celery worker ekleyerek throughput artırılır.
- **Dayanıklı fetch:** Üstel backoff, jitter ve domain bazlı nezaket gecikmesiyle yeniden deneme.
- **Tekilleştirme:** RedisBloom varsa kullanır, yoksa bellek içi fallback'e düşer.
- **Artımlı mod:** Sayfa içeriği değiştiğinde yeniden işler.
- **AI destekli mod:** Browserless Chrome + Ollama LLM ile dinamik kazıma.
- **Dead-letter kuyruğu:** Başarısız görevler sonradan incelenmek üzere yakalanır.
- **Gözlemlenebilirlik:** Prometheus metrikleri, Flower görev izleme ve Jaeger dağıtık izleme.
- **Web dashboard:** `http://localhost:8000` adresinde sunulan karanlık tema kontrol paneli.

### Hızlı Başlangıç

#### Seçenek A — Sıfır altyapı (yerel SQLite)

```bash
pip install -r requirements.txt
python run_local.py --pages 2
```

#### Seçenek B — Tam dağıtık mod (Docker)

```bash
docker compose up --build
```

Ardından bir kazıma işi başlatın:

```bash
curl -X POST http://localhost:8000/scrape \
  -H "Content-Type: application/json" \
  -H "X-API-Key: BENIM_GIZLI_SIFREM_123" \
  -d '{"max_pages": 5, "chunk_size": 10}'
```

İlerlemeyi kontrol edin:

```bash
curl http://localhost:8000/stats
curl http://localhost:8000/health
```

Arayüzleri açın:

- **Web Arayüzü:** http://localhost:8000
- **Flower:** http://localhost:5555
- **Metrikler:** http://localhost:8000/metrics
- **Jaeger:** http://localhost:16686

### API Uç Noktaları

Tüm `POST` uç noktaları `X-API-Key` header'ı gerektirir.

| Uç Nokta | Metot | Açıklama |
|----------|-------|----------|
| `/` | GET | Web arayüzü (`index.html`). |
| `/scrape` | POST | Katalog tarama (standart mod). |
| `/scrape-dynamic` | POST | Katalog tarama (AI / Playwright modu). |
| `/scrape-one` | POST | Tek URL kazıma; `force=true` dedup'u atlar. |
| `/status/{task_id}` | GET | Celery görev durumu. |
| `/stats` | GET | Kitap sayısı + tekilleştirme backend bilgisi. |
| `/books` | GET | Veritabanındaki kitaplar (sayfalı). |
| `/dead-letter` | GET | İnceleme için yakalanan başarısız görevler. |
| `/health` | GET | Derin sağlık kontrolü: Redis + PostgreSQL. |
| `/metrics` | GET | Prometheus metrik endpoint'i. |

### Konfigürasyon

Önemli ortam değişkenleri (tam liste için `core/config.py`):

| Değişken | Default | Açıklama |
|----------|---------|----------|
| `SCRAPE_BASE_URL` | `https://books.toscrape.com/` | Hedef site |
| `REDIS_URL` | `redis://localhost:6379/0` | Broker + Bloom filter |
| `DATABASE_URL` | `sqlite:///scrapehub.db` | Üretimde PostgreSQL önerilir |
| `API_KEY` | `BENIM_GIZLI_SIFREM_123` | FastAPI endpoint koruması |
| `REQUEST_DELAY` | `0.5` | İstekler arası nezaket gecikmesi |
| `MAX_CONCURRENCY` | `4` | Worker eşzamanlılık tabanı |
| `MAX_RETRIES` | `3` | Başarısız fetch için yeniden deneme |
| `INCREMENTAL` | `false` | Sadece içerik değiştiğinde yeniden işle |
| `BROWSERLESS_URL` | `ws://localhost:3000` | AI modu için headless Chrome |
| `OLLAMA_URL` | `http://127.0.0.1:11434` | Yerel LLM endpoint'i |
| `JAEGER_ENDPOINT` | `http://localhost:4318/v1/traces` | OpenTelemetry trace'leri |

### Test

```bash
pytest -q
```

`tests/conftest.py` testleri izole eder: geçici SQLite veritabanı ve bellek içi tekilleştirme kullanır.

### Etik & Yasal Uyarı

Bu proje, izin veren hedeflerde eğitim amaçlı kullanım içindir. `core/fetcher.py`, `robots.txt`'e saygı duyar ve nezaket gecikmesi uygular. Başka domain'leri kazırken hedef sitenin Kullanım Koşulları ve ilgili veri gizliliği yasalarına (GDPR/KVKK) uyma sorumluluğu tamamen kullanıcıya aittir.

---

## Architecture

```
  ┌──────────────┐   POST /scrape    ┌──────────────────┐
  │  Client /    │ ───────────────► │  FastAPI (API)   │   Layer 1: Orchestrator
  │  Cron job    │  (X-API-Key)     │   app/main.py    │
  └──────────────┘                  └────────┬─────────┘
                                              │ .delay()
                                     ┌────────▼─────────┐
                                     │  Redis (broker)  │   Layer 1: Queue
                                     └────────┬─────────┘
                                              │
                              ┌───────────────▼───────────────┐
                              │   Celery Workers (xN)         │
                              │   workers/tasks.py            │
                              │                               │
                              │  1. Dedup  (Bloom Filter)     │◄─ Layer 2
                              │  2. Fetch  (curl_cffi /       │◄─ Layer 3+4
                              │            Playwright + LLM)  │
                              │  3. Parse  (JSON-LD/CSS/regex)│◄─ Layer 5
                              │  4. Store  (ON CONFLICT)      │
                              └───────────────┬───────────────┘
                                              │
                                     ┌────────▼──────────┐
                                     │  PostgreSQL /     │   Storage
                                     │  SQLite           │
                                     └───────────────────┘
```

### Service Map (Docker Compose)

| Service | Purpose | Port |
|---------|---------|------|
| `api` | FastAPI gateway + static dashboard | `8000` |
| `worker` | Celery task workers | — |
| `redis` | Broker + Bloom filter + dead-letter | `6379`, `8001` |
| `postgres` | Persistent relational storage | `5432` |
| `flower` | Celery monitoring UI | `5555` |
| `browserless` | Headless Chrome for dynamic/AI mode | `3000` |
| `jaeger` | Distributed tracing UI | `16686` |

---

*README: English / Türkçe — bilingual documentation.*

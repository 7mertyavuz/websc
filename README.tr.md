# ScrapeHub — AI Destekli Web Scraping Pipeline'ı

[![CI](https://github.com/7mertyavuz/websc/actions/workflows/ci.yml/badge.svg)](https://github.com/7mertyavuz/websc/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**[English](README.md) | [Türkçe](README.tr.md)**

**FastAPI**, **Celery**, **Redis**, **PostgreSQL** ve **OpenTelemetry** ile kurulmuş, üretime hazır, yatayda ölçeklenebilir bir web scraping pipeline'ıdır. Katalog tarama, tekilleştirme, dayanıklı fetch, çok kademeli parse ve kalıcı depolama işlemlerini yönetir. İsteğe bağlı olarak Playwright + Ollama ile desteklenen AI destekli modu da bulunur.

> **Durum:** Bu proje eğitim amaçlı olarak `books.toscrape.com` üzerinde çalışır, ancak altyapı kurumsal düzeyde scraping iş yükleri için tasarlanmıştır.
>
> 📖 **Mimariyi derinlemesine incelemek için → [DOKUMANTASYON.md](DOKUMANTASYON.md)**

---

## ScrapeHub Nedir?

ScrapeHub, bir web sitesini yapılandırılmış veriye dönüştüren ve veritabanına yazan dağıtık bir web scraping pipeline'ıdır. Beş bağımsız katman üzerine kuruludur:

1. **Orkestratör** — İstekleri alan ve işleri kuyruğa koyan FastAPI ağ geçidi.
2. **Kuyruk** — Redis destekli Celery broker'ı ile görev dağıtımı.
3. **Tekilleştirme** — Gereksiz işi önleyen Bloom filter + içerik hash'i.
4. **Fetch & Parse** — Stealth için `curl_cffi`, JS ağırlıklı sayfalar için Playwright ve dayanıklı fallback parser.
5. **Depolama** — Atomik upsert destekli SQLAlchemy + PostgreSQL/SQLite.

## Öne Çıkan Özellikler

- **Mikroservis odaklı:** API, worker'lar, Redis, Postgres ve Flower ayrı servisler olarak çalışır.
- **Yatay ölçeklenebilir:** Daha fazla Celery worker ekleyerek throughput artırılır.
- **Dayanıklı fetch:** Üstel backoff, jitter ve domain bazlı nezaket gecikmesiyle yeniden deneme.
- **Tekilleştirme:** RedisBloom varsa kullanır, yoksa bellek içi fallback'e düşer.
- **Artımlı mod:** Sayfa içeriği değiştiğinde yeniden işler.
- **AI destekli mod:** Browserless Chrome + Ollama LLM ile dinamik kazıma.
- **Dead-letter kuyruğu:** Başarısız görevler sonradan incelenmek üzere yakalanır.
- **Gözlemlenebilirlik:** Prometheus metrikleri, Flower görev izleme ve Jaeger dağıtık izleme.
- **Web dashboard:** `http://localhost:8000` adresinde sunulan karanlık tema kontrol paneli.

## Hızlı Başlangıç

### Seçenek A — Sıfır altyapı (yerel SQLite)

```bash
pip install -r requirements.txt
python run_local.py --pages 2
```

### Seçenek B — Tam dağıtık mod (Docker)

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

## API Uç Noktaları

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

## Konfigürasyon

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

## Test

```bash
pytest -q
```

`tests/conftest.py` testleri izole eder: geçici SQLite veritabanı ve bellek içi tekilleştirme kullanır.

## Mimari

```
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
                              │  2. Fetch  (curl_cffi /       │◄─ Katman 3+4
                              │            Playwright + LLM)  │
                              │  3. Parse  (JSON-LD/CSS/regex)│◄─ Katman 5
                              │  4. Store  (ON CONFLICT)      │
                              └───────────────┬───────────────┘
                                              │
                                     ┌────────▼──────────┐
                                     │  PostgreSQL /     │   Depolama
                                     │  SQLite           │
                                     └───────────────────┘
```

### Servis Haritası (Docker Compose)

| Servis | Amaç | Port |
|--------|------|------|
| `api` | FastAPI ağ geçidi + statik dashboard | `8000` |
| `worker` | Celery görev worker'ları | — |
| `redis` | Broker + Bloom filter + dead-letter | `6379`, `8001` |
| `postgres` | Kalıcı ilişkisel depolama | `5432` |
| `flower` | Celery izleme arayüzü | `5555` |
| `browserless` | Dinamik/AI modu için headless Chrome | `3000` |
| `jaeger` | Dağıtık izleme arayüzü | `16686` |

## Etik & Yasal Uyarı

Bu proje, izin veren hedeflerde eğitim amaçlı kullanım içindir. `core/fetcher.py`, `robots.txt`'e saygı duyar ve nezaket gecikmesi uygular. Başka domain'leri kazırken hedef sitenin Kullanım Koşulları ve ilgili veri gizliliği yasalarına (GDPR/KVKK) uyma sorumluluğu tamamen kullanıcıya aittir.

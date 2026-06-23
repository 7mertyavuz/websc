"""
Katman 1: API Gateway (FastAPI).

Senin planındaki orkestratör. Kullanıcı/cron buraya istek atar,
FastAPI işi Celery kuyruğuna devreder ve hemen döner (async, non-blocking).

Endpoint'ler:
  POST /scrape       -> bir kazıma işi başlat (katalogu gez)
  GET  /status/{id}  -> Celery görev durumunu sorgula
  GET  /stats        -> DB'deki kitap sayısı + dedup backend bilgisi
  GET  /health       -> ayakta mı?

Celery ayakta olmasa da API import edilebilsin; gerçek dağıtım .delay() anında olur.
"""
from __future__ import annotations
from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

from core.config import settings
from core.dedup import dedup
from core.logging import get_logger
from core.metrics import metrics
from storage.db import count_books, init_db, ping_db
from workers.tasks import discover_catalog, scrape_book

logger = get_logger(__name__)

app = FastAPI(title="ScrapeHub", version="1.0", description="Eğitim amaçlı dağıtık scraping pipeline")

init_db()


class ScrapeRequest(BaseModel):
    start_url: str | None = None
    max_pages: int = 5
    chunk_size: int = 10   # >1 ise URL'ler Celery chunks ile gruplanır; <=1 ise tek tek


class ScrapeOneRequest(BaseModel):
    url: str


def _check_redis() -> dict:
    """Redis'e gerçekten PING atıp bağlanabildiğimizi doğrula."""
    try:
        import redis  # lazy import: redis kurulu değilse de API ayağa kalksın
    except ImportError as e:
        return {"status": "fail", "error": f"redis client yok: {e!r}"}
    try:
        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2)
        client.ping()
        return {"status": "ok"}
    except Exception as e:
        return {"status": "fail", "error": repr(e)}


def _check_db() -> dict:
    """DB'ye gerçekten 'SELECT 1' atıp bağlanabildiğimizi doğrula."""
    try:
        ping_db()
        return {"status": "ok"}
    except Exception as e:
        return {"status": "fail", "error": repr(e)}


@app.get("/health")
def health() -> JSONResponse:
    """
    Derin health-check: 'ayakta mı' yetmez; Redis'e ve DB'ye GERÇEKTEN bağlanabiliyor
    muyuz onu döndürür. Bağımlılıklardan biri bile fail ise HTTP 503, hepsi ok ise 200.
    """
    checks = {"redis": _check_redis(), "database": _check_db()}
    all_ok = all(c["status"] == "ok" for c in checks.values())
    body = {
        "status": "ok" if all_ok else "degraded",
        "target": settings.base_url,
        "dedup_backend": dedup.backend,
        "checks": checks,
    }
    if not all_ok:
        logger.warning("health-check degraded: %s", checks)
    return JSONResponse(status_code=200 if all_ok else 503, content=body)


@app.post("/scrape")
def start_scrape(req: ScrapeRequest) -> dict:
    """Katalog tarama işini kuyruğa atar, görev id'si döndürür."""
    task = discover_catalog.delay(req.start_url, req.max_pages, req.chunk_size)
    return {
        "task_id": task.id,
        "queued": True,
        "max_pages": req.max_pages,
        "chunk_size": req.chunk_size,
    }


@app.post("/scrape-one")
def scrape_single(req: ScrapeOneRequest) -> dict:
    """Tek bir URL'i kuyruğa atar."""
    task = scrape_book.delay(req.url)
    return {"task_id": task.id, "queued": True, "url": req.url}


@app.get("/status/{task_id}")
def status(task_id: str) -> dict:
    from workers.celery_app import celery_app
    res = celery_app.AsyncResult(task_id)
    return {"task_id": task_id, "state": res.state, "result": res.result if res.ready() else None}


@app.get("/stats")
def stats() -> dict:
    return {"books_in_db": count_books(), "dedup_backend": dedup.backend}


@app.get("/metrics", response_class=PlainTextResponse)
def prometheus_metrics() -> PlainTextResponse:
    """
    Prometheus text exposition formatında metrikler:
      - scrapehub_pages_processed_total  (counter) işlenen sayfa
      - scrapehub_failed_fetch_total     (counter) başarısız fetch
      - scrapehub_dead_letter_depth      (gauge)   dead-letter kuyruk derinliği
      - scrapehub_db_books               (gauge)   DB'deki kayıt sayısı
    Sayaçlar Redis'te paylaşımlıdır (API + worker'lar aynı değeri görür).
    """
    return PlainTextResponse(content=metrics.render(), media_type="text/plain; version=0.0.4")

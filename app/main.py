"""
Katman 1: API Gateway (FastAPI).
X-API-Key ile korunmaktadır.
"""
from __future__ import annotations
from fastapi import FastAPI, Depends, HTTPException, Security
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel

from core.config import settings
from core.dedup import dedup
from core.logging import get_logger
from core.metrics import metrics
from storage.db import count_books, init_db, ping_db
from workers.tasks import discover_catalog, scrape_book

logger = get_logger(__name__)

app = FastAPI(title="ScrapeHub", version="1.0", description="Kurumsal Web Scraping Pipeline")

init_db()

# --- Güvenlik ---
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)

def verify_api_key(api_key: str = Security(api_key_header)):
    if api_key != settings.api_key:
        raise HTTPException(status_code=403, detail="Geçersiz yetki (X-API-Key hatalı)")
    return api_key

class ScrapeRequest(BaseModel):
    start_url: str | None = None
    max_pages: int = 5
    chunk_size: int = 10

class ScrapeOneRequest(BaseModel):
    url: str
    force: bool = False # Bloom filter atlamak için

def _check_redis() -> dict:
    try:
        import redis
    except ImportError as e:
        return {"status": "fail", "error": f"redis client yok: {e!r}"}
    try:
        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2)
        client.ping()
        return {"status": "ok"}
    except Exception as e:
        return {"status": "fail", "error": repr(e)}

def _check_db() -> dict:
    try:
        ping_db()
        return {"status": "ok"}
    except Exception as e:
        return {"status": "fail", "error": repr(e)}

@app.get("/health")
def health() -> JSONResponse:
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
def start_scrape(req: ScrapeRequest, api_key: str = Depends(verify_api_key)) -> dict:
    task = discover_catalog.delay(req.start_url, req.max_pages, req.chunk_size)
    return {
        "task_id": task.id,
        "queued": True,
        "max_pages": req.max_pages,
        "chunk_size": req.chunk_size,
    }

@app.post("/scrape-one")
def scrape_single(req: ScrapeOneRequest, api_key: str = Depends(verify_api_key)) -> dict:
    task = scrape_book.delay(req.url, req.force)
    return {"task_id": task.id, "queued": True, "url": req.url, "forced": req.force}

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
    return PlainTextResponse(content=metrics.render(), media_type="text/plain; version=0.0.4")

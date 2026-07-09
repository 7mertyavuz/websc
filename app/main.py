"""
Katman 1: API Gateway (FastAPI).
OpenTelemetry, yeni AI uç noktaları ve web arayüzü ile güncellendi.
"""
from __future__ import annotations
from contextlib import suppress
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.security.api_key import APIKeyHeader
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.config import settings
from core.dedup import dedup
from core.logging import get_logger
from core.metrics import metrics
from storage.db import count_books, get_books, init_db, ping_db

# Sisteme doğrudan ana Celery uygulamamızı tanıtıyoruz
from workers.celery_app import celery_app

from core.tracing import setup_tracing
setup_tracing("scrapehub-api")
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

logger = get_logger(__name__)

app = FastAPI(title="ScrapeHub AI", version="2.1", description="Otonom Web Scraping Pipeline")

# CORS: frontend (yerel geliştirme veya farklı domain) API'ye erişebilsin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FastAPIInstrumentor.instrument_app(app)

init_db()

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)

# Frontend dosyalarını servis et
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if FRONTEND_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


def verify_api_key(api_key: str = Security(api_key_header)):
    if api_key != settings.api_key:
        raise HTTPException(status_code=403, detail="Geçersiz yetki")
    return api_key


class ScrapeRequest(BaseModel):
    start_url: str | None = None
    max_pages: int = 5
    chunk_size: int = 10
    webhook_url: str | None = None


class ScrapeOneRequest(BaseModel):
    url: str
    force: bool = False


@app.get("/")
def root():
    """Ana sayfa olarak frontend'i döndür."""
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"message": "ScrapeHub API çalışıyor", "docs": "/docs"}


@app.post("/scrape")
def start_scrape(req: ScrapeRequest, api_key: str = Depends(verify_api_key)) -> dict:
    task = celery_app.send_task(
        "workers.discover_catalog",
        kwargs={
            "start_url": req.start_url,
            "max_pages": req.max_pages,
            "chunk_size": req.chunk_size,
            "webhook_url": req.webhook_url,
            "use_ai": False,
        },
    )
    return {"task_id": task.id, "queued": True, "type": "standard"}


@app.post("/scrape-dynamic")
def start_dynamic_scrape(req: ScrapeRequest, api_key: str = Depends(verify_api_key)) -> dict:
    task = celery_app.send_task(
        "workers.discover_catalog",
        kwargs={
            "start_url": req.start_url,
            "max_pages": req.max_pages,
            "chunk_size": req.chunk_size,
            "webhook_url": req.webhook_url,
            "use_ai": True,
        },
    )
    return {"task_id": task.id, "queued": True, "type": "ai_agentic"}


@app.post("/scrape-one")
def scrape_single(req: ScrapeOneRequest, api_key: str = Depends(verify_api_key)) -> dict:
    task = celery_app.send_task(
        "workers.scrape_book",
        kwargs={"url": req.url, "force": req.force, "use_ai": False},
    )
    return {"task_id": task.id, "queued": True, "url": req.url}


@app.get("/status/{task_id}")
def status(task_id: str) -> dict:
    res = celery_app.AsyncResult(task_id)
    info: dict = {"task_id": task_id, "state": res.state}
    if res.ready():
        with suppress(Exception):
            info["result"] = res.get(propagate=False)
    return info


@app.get("/stats")
def stats() -> dict:
    return {"books_in_db": count_books(), "dedup_backend": dedup.backend}


@app.get("/books")
def list_books(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    """Veritabanındaki kitapları sayfalayarak döndür."""
    books, total = get_books(limit=limit, offset=offset)
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "books": [b.model_dump() for b in books],
    }


@app.get("/dead-letter")
def list_dead_letter(limit: int = Query(100, ge=1, le=1000)) -> dict:
    """Son başarısız görevleri (dead-letter kuyruğu) döndür."""
    items: list[dict] = []
    client = getattr(dedup, "_client", None)
    if client:
        try:
            raw_items = client.lrange("scrapehub:dead_letter", 0, limit - 1)
            import json
            for raw in raw_items:
                with suppress(Exception):
                    items.append(json.loads(raw))
        except Exception as exc:
            logger.warning("dead-letter okunamadı: %r", exc)
    return {"items": items, "count": len(items)}


@app.get("/health")
def health() -> dict:
    """Derin health-check: Redis ve PostgreSQL erişilebilirliğini kontrol et."""
    checks = {
        "redis": False,
        "database": False,
    }
    try:
        from celery.app.control import Control
        ctrl = Control(celery_app)
        checks["redis"] = ctrl.ping() is not None
    except Exception as exc:
        logger.debug("redis health check hatası: %r", exc)
        # Broker'a direkt ping deneyelim
        try:
            checks["redis"] = celery_app.connection().heartbeat_check()
        except Exception:
            checks["redis"] = False

    try:
        checks["database"] = ping_db()
    except Exception as exc:
        logger.debug("db health check hatası: %r", exc)
        checks["database"] = False

    healthy = all(checks.values())
    response = {
        "status": "healthy" if healthy else "unhealthy",
        "target": settings.base_url,
        "dedup_backend": dedup.backend,
        "checks": checks,
    }
    status_code = 200 if healthy else 503
    return JSONResponse(content=response, status_code=status_code)


@app.get("/metrics", response_class=PlainTextResponse)
def prometheus_metrics() -> PlainTextResponse:
    return PlainTextResponse(content=metrics.render(), media_type="text/plain; version=0.0.4")

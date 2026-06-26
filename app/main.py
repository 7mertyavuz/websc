"""
Katman 1: API Gateway (FastAPI).
OpenTelemetry ve Yeni AI Uç Noktaları ile güncellendi.
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

# Sisteme doğrudan ana Celery uygulamamızı tanıtıyoruz
from workers.celery_app import celery_app

from core.tracing import setup_tracing
setup_tracing("scrapehub-api")
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

logger = get_logger(__name__)

app = FastAPI(title="ScrapeHub AI", version="2.0", description="Otonom Web Scraping Pipeline")
FastAPIInstrumentor.instrument_app(app)

init_db()

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)

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

@app.post("/scrape")
def start_scrape(req: ScrapeRequest, api_key: str = Depends(verify_api_key)) -> dict:
    # .delay yerine doğrudan send_task ile Redis'e zorluyoruz
    task = celery_app.send_task(
        "workers.discover_catalog",
        kwargs={
            "start_url": req.start_url,
            "max_pages": req.max_pages,
            "chunk_size": req.chunk_size,
            "webhook_url": req.webhook_url,
            "use_ai": False
        }
    )
    return {"task_id": task.id, "queued": True, "type": "standard"}

@app.post("/scrape-dynamic")
def start_dynamic_scrape(req: ScrapeRequest, api_key: str = Depends(verify_api_key)) -> dict:
    # AI işlemi için zorla Redis'e gönderiyoruz
    task = celery_app.send_task(
        "workers.discover_catalog",
        kwargs={
            "start_url": req.start_url,
            "max_pages": req.max_pages,
            "chunk_size": req.chunk_size,
            "webhook_url": req.webhook_url,
            "use_ai": True
        }
    )
    return {"task_id": task.id, "queued": True, "type": "ai_agentic"}

@app.post("/scrape-one")
def scrape_single(req: ScrapeOneRequest, api_key: str = Depends(verify_api_key)) -> dict:
    task = celery_app.send_task(
        "workers.scrape_book",
        kwargs={"url": req.url, "force": req.force, "use_ai": False}
    )
    return {"task_id": task.id, "queued": True, "url": req.url}

@app.get("/status/{task_id}")
def status(task_id: str) -> dict:
    res = celery_app.AsyncResult(task_id)
    return {"task_id": task_id, "state": res.state}

@app.get("/stats")
def stats() -> dict:
    return {"books_in_db": count_books(), "dedup_backend": dedup.backend}

@app.get("/metrics", response_class=PlainTextResponse)
def prometheus_metrics() -> PlainTextResponse:
    return PlainTextResponse(content=metrics.render(), media_type="text/plain; version=0.0.4")

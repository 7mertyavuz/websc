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
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from core.config import settings
from core.dedup import dedup
from storage.db import count_books, init_db
from workers.tasks import discover_catalog, scrape_book

app = FastAPI(title="ScrapeHub", version="1.0", description="Eğitim amaçlı dağıtık scraping pipeline")

init_db()


class ScrapeRequest(BaseModel):
    start_url: str | None = None
    max_pages: int = 5
    chunk_size: int = 10   # >1 ise URL'ler Celery chunks ile gruplanır; <=1 ise tek tek


class ScrapeOneRequest(BaseModel):
    url: str


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "target": settings.base_url, "dedup_backend": dedup.backend}


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

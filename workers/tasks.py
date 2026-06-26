"""
Worker görevleri = pipeline'ın çalışan kalbi.
Webhook (Olay Güdümlü) ve Otonom (Playwright/AI) mantığı eklendi.
"""
from __future__ import annotations
import json
import requests
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from celery import shared_task, Task, chord

from core.config import settings
from core.dedup import dedup
from core.fetcher import fetcher
from core.logging import get_logger
from core.metrics import metrics
from parser.extract import parse
from storage.db import init_db, upsert_book
from core.browser import fetch_with_browser
from parser.ai_extract import parse_with_llama

logger = get_logger(__name__)
init_db()

DEAD_LETTER_KEY = "scrapehub:dead_letter"

class FetchError(Exception): pass

def push_dead_letter(payload: dict) -> None:
    data = json.dumps(payload, ensure_ascii=False)
    client = getattr(dedup, "_client", None)
    if client:
        try:
            client.rpush(DEAD_LETTER_KEY, data)
            return
        except Exception: pass
    logger.error("[dead-letter] %s", data)

class DeadLetterTask(Task):
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        push_dead_letter({
            "task": self.name,
            "task_id": task_id,
            "args": list(args),
            "error": repr(exc),
        })

# --- KONU 4: Event-Driven Webhook Görevi ---
@shared_task(name="workers.webhook_callback")
def webhook_callback(results, webhook_url: str, meta: dict):
    """Tüm URL'ler kazındıktan SONRA otomatik çalışır ve müşteriye POST atar."""
    successful = sum(1 for r in results if isinstance(r, dict) and r.get("status") in ["ok", "updated"])
    payload = {
        "event": "scraping_completed",
        "meta": meta,
        "total_processed": len(results),
        "successful_inserts": successful
    }
    try:
        logger.info(f"Webhook tetikleniyor -> {webhook_url}")
        requests.post(webhook_url, json=payload, timeout=5)
    except Exception as e:
        logger.error(f"Webhook gönderilemedi: {e}")

@shared_task(
    bind=True, base=DeadLetterTask, name="workers.scrape_book",
    autoretry_for=(FetchError,), retry_backoff=True, retry_jitter=True,
    max_retries=None, retry_kwargs={"max_retries": settings.max_retries},
)
def scrape_book(self, url: str, force: bool = False, use_ai: bool = False) -> dict:
    # URL dedup ve incremental kontrolleri
    if not force:
        if settings.incremental:
            # İçerik hash için mecburen fetch etmeliyiz
            pass 
        elif dedup.check_and_mark(url):
            return {"url": url, "status": "skipped_duplicate"}

    # --- KONU 1, 2, 3: Karar Ağacı ---
    if use_ai:
        # Dinamik (Playwright) Fetch + Llama Parse
        html = fetch_with_browser(url)
        if not html:
            metrics.inc("failed_fetch")
            raise FetchError(f"Browser fetch failed: {url}")
        
        book = parse_with_llama(html, url)
    else:
        # Standart (curl_cffi) Fetch + CSS Parse
        html = fetcher.get(url)
        if not html:
            metrics.inc("failed_fetch")
            raise FetchError(f"Fetch failed: {url}")
            
        book = parse(html, url)

    # Incremental (İçerik) Kontrolü (Html çektikten sonra)
    if settings.incremental and not force:
        if not dedup.content_changed(url, html):
            dedup.mark(url)
            return {"url": url, "status": "skipped_unchanged"}

    if not book:
        return {"url": url, "status": "parse_failed"}

    upsert_book(book)
    dedup.mark(url)
    metrics.inc("pages_processed")
    return {"url": url, "status": "updated" if settings.incremental else "ok", "title": book.title, "price": book.price}

@shared_task(bind=True, name="workers.discover_catalog")
def discover_catalog(
    self,
    start_url: str | None = None,
    max_pages: int = 5,
    chunk_size: int = 10,
    webhook_url: str | None = None,
    use_ai: bool = False
) -> dict:
    base = settings.base_url
    page_url = start_url or urljoin(base, "catalogue/page-1.html")
    pages_done = 0
    book_urls: list[str] = []

    while page_url and pages_done < max_pages:
        html = fetcher.get(page_url)
        if not html: break
        soup = BeautifulSoup(html, "html.parser")

        for a in soup.select("article.product_pod h3 a"):
            href = a.get("href", "")
            book_urls.append(urljoin(page_url, href))

        nxt = soup.select_one("li.next a")
        page_url = urljoin(page_url, nxt.get("href")) if nxt else None
        pages_done += 1

    if chunk_size and chunk_size > 1 and book_urls:
        items = [(u, False, use_ai) for u in book_urls]
        task_group = scrape_book.chunks(items, chunk_size).group()
        
        # Webhook varsa Celery Chord ile bağla, yoksa normal asenkron çalıştır
        if webhook_url:
            meta = {"pages_scanned": pages_done, "books_dispatched": len(book_urls), "ai_used": use_ai}
            callback = webhook_callback.s(webhook_url, meta)
            group_result = chord(task_group)(callback)
        else:
            group_result = task_group.apply_async()
            
        num_chunks = (len(book_urls) + chunk_size - 1) // chunk_size
        return {
            "mode": "chunked",
            "webhook_attached": bool(webhook_url),
            "books_dispatched": len(book_urls),
            "chunks": num_chunks,
            "group_id": getattr(group_result, "id", None),
        }

    for u in book_urls:
        scrape_book.delay(u, force=False, use_ai=use_ai)
    
    return {
        "pages_scanned": pages_done,
        "books_dispatched": len(book_urls),
        "mode": "per_url",
    }

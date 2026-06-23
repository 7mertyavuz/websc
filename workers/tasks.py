"""
Worker görevleri = pipeline'ın çalışan kalbi.
"""
from __future__ import annotations
import json
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from celery import shared_task, Task

from core.config import settings
from core.dedup import dedup
from core.fetcher import fetcher
from core.logging import get_logger
from core.metrics import metrics
from parser.extract import parse
from storage.db import init_db, upsert_book

logger = get_logger(__name__)

init_db()

DEAD_LETTER_KEY = "scrapehub:dead_letter"

class FetchError(Exception):
    """Sayfa çekilemedi."""

def push_dead_letter(payload: dict) -> None:
    data = json.dumps(payload, ensure_ascii=False)
    client = getattr(dedup, "_client", None)
    if client is not None:
        try:
            client.rpush(DEAD_LETTER_KEY, data)
            return
        except Exception:
            pass
    logger.error("[dead-letter] %s", data)

class DeadLetterTask(Task):
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        push_dead_letter({
            "task": self.name,
            "task_id": task_id,
            "args": list(args),
            "error": repr(exc),
        })

@shared_task(
    bind=True,
    base=DeadLetterTask,
    name="workers.scrape_book",
    autoretry_for=(FetchError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=None,
    retry_kwargs={"max_retries": settings.max_retries},
)
def scrape_book(self, url: str, force: bool = False) -> dict:
    if settings.incremental:
        html = fetcher.get(url)
        if not html:
            metrics.inc("failed_fetch")
            raise FetchError(f"fetch failed (incremental): {url}")
        
        # Eğer FORCE aktif DEĞİLSE ve içerik DEĞİŞMEDİYSE atla
        if not force and not dedup.content_changed(url, html):
            dedup.mark(url)
            return {"url": url, "status": "skipped_unchanged"}
            
        book = parse(html, url)
        if not book:
            return {"url": url, "status": "parse_failed"}
        upsert_book(book)
        dedup.mark(url)
        metrics.inc("pages_processed")
        return {"url": url, "status": "updated", "title": book.title, "price": book.price}

    # Klasik mod: FORCE aktif DEĞİLSE ve URL görüldüyse atla
    if not force and dedup.check_and_mark(url):
        return {"url": url, "status": "skipped_duplicate"}

    html = fetcher.get(url)
    if not html:
        metrics.inc("failed_fetch")
        raise FetchError(f"fetch failed: {url}")

    book = parse(html, url)
    if not book:
        return {"url": url, "status": "parse_failed"}

    upsert_book(book)
    metrics.inc("pages_processed")
    return {"url": url, "status": "ok", "title": book.title, "price": book.price}

@shared_task(bind=True, name="workers.discover_catalog")
def discover_catalog(
    self,
    start_url: str | None = None,
    max_pages: int = 5,
    chunk_size: int = 10,
) -> dict:
    base = settings.base_url
    page_url = start_url or urljoin(base, "catalogue/page-1.html")
    pages_done = 0
    book_urls: list[str] = []

    while page_url and pages_done < max_pages:
        html = fetcher.get(page_url)
        if not html:
            break
        soup = BeautifulSoup(html, "html.parser")

        for a in soup.select("article.product_pod h3 a"):
            href = a.get("href", "")
            book_urls.append(urljoin(page_url, href))

        nxt = soup.select_one("li.next a")
        page_url = urljoin(page_url, nxt.get("href")) if nxt else None
        pages_done += 1

    if chunk_size and chunk_size > 1 and book_urls:
        items = [(u,) for u in book_urls]
        group_result = scrape_book.chunks(items, chunk_size).group().apply_async()
        num_chunks = (len(book_urls) + chunk_size - 1) // chunk_size
        return {
            "pages_scanned": pages_done,
            "books_dispatched": len(book_urls),
            "mode": "chunked",
            "chunk_size": chunk_size,
            "chunks": num_chunks,
            "group_id": getattr(group_result, "id", None),
        }

    for u in book_urls:
        # Eski sistemde tek tek yollarken varsayılan olarak force=False gidecek
        scrape_book.delay(u)
    return {
        "pages_scanned": pages_done,
        "books_dispatched": len(book_urls),
        "mode": "per_url",
        "chunk_size": chunk_size,
    }

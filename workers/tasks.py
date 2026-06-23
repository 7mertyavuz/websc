"""
Worker görevleri = pipeline'ın çalışan kalbi.

Akış (senin 6 adımlık senaryonun bypass'sız hali):
  1. discover_catalog : katalog sayfalarını gezip kitap URL'lerini bulur
  2. scrape_book      : tek bir kitap URL'ini -> dedup -> fetch -> parse -> DB

Her kitap URL'i ayrı bir Celery görevi olur; 50 worker varsa 50 kitap aynı anda işlenir.
"""
from __future__ import annotations
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from celery import shared_task

from core.config import settings
from core.dedup import dedup
from core.fetcher import fetcher
from parser.extract import parse
from storage.db import init_db, upsert_book

init_db()


@shared_task(bind=True, name="workers.scrape_book")
def scrape_book(self, url: str) -> dict:
    """Tek kitabı işle. Dedup -> fetch -> parse -> kaydet."""
    # 1. Dedup: son 24 saatte çektiysek atla (bütçe/zaman tasarrufu).
    if dedup.check_and_mark(url):
        return {"url": url, "status": "skipped_duplicate"}

    # 2. Fetch (nazik, retry'lı).
    html = fetcher.get(url)
    if not html:
        return {"url": url, "status": "fetch_failed"}

    # 3. Parse (CSS ya da LLM).
    book = parse(html, url)
    if not book:
        return {"url": url, "status": "parse_failed"}

    # 4. Kaydet.
    upsert_book(book)
    return {"url": url, "status": "ok", "title": book.title, "price": book.price}


@shared_task(bind=True, name="workers.discover_catalog")
def discover_catalog(self, start_url: str | None = None, max_pages: int = 5) -> dict:
    """
    Katalog sayfalarını gez, her kitap için scrape_book görevi kuyruğa at.
    max_pages ile sınırlı tutuyoruz ki demo nazik kalsın.
    """
    base = settings.base_url
    page_url = start_url or urljoin(base, "catalogue/page-1.html")
    dispatched = 0
    pages_done = 0

    while page_url and pages_done < max_pages:
        html = fetcher.get(page_url)
        if not html:
            break
        soup = BeautifulSoup(html, "html.parser")

        # Bu sayfadaki kitap linklerini topla.
        for a in soup.select("article.product_pod h3 a"):
            href = a.get("href", "")
            book_url = urljoin(page_url, href)
            scrape_book.delay(book_url)   # <-- kuyruğa at, worker alsın
            dispatched += 1

        # Sonraki sayfa var mı?
        nxt = soup.select_one("li.next a")
        page_url = urljoin(page_url, nxt.get("href")) if nxt else None
        pages_done += 1

    return {"pages_scanned": pages_done, "books_dispatched": dispatched}

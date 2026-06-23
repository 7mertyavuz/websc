"""
run_local.py — Redis/Celery KURMADAN tüm pipeline'ı senkron çalıştırır.

Amaç: "önce çalıştığını gör, sonra dağıtık moda geç."
Aynı fonksiyonları (dedup, fetcher, parse, storage) kullanır ama Celery'ye
.delay() ile atmak yerine doğrudan çağırır.

Kullanım:
    python run_local.py --pages 2
"""
from __future__ import annotations
import argparse
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core.config import settings
from core.dedup import dedup
from core.fetcher import fetcher
from parser.extract import parse
from storage.db import count_books, init_db, upsert_book


def scrape_book_sync(url: str) -> str:
    if dedup.check_and_mark(url):
        return "skip(dup)"
    html = fetcher.get(url)
    if not html:
        return "fetch_failed"
    book = parse(html, url)
    if not book:
        return "parse_failed"
    upsert_book(book)
    return f"ok: {book.title[:40]} (£{book.price})"


def run(max_pages: int) -> None:
    init_db()
    print(f"Hedef: {settings.base_url}")
    print(f"Dedup backend: {dedup.backend}")
    print(f"DB: {settings.database_url}\n")

    page_url = urljoin(settings.base_url, "catalogue/page-1.html")
    pages = 0
    total = 0

    while page_url and pages < max_pages:
        html = fetcher.get(page_url)
        if not html:
            break
        soup = BeautifulSoup(html, "html.parser")
        links = soup.select("article.product_pod h3 a")
        print(f"--- Sayfa {pages + 1}: {len(links)} kitap bulundu ---")

        for a in links:
            book_url = urljoin(page_url, a.get("href", ""))
            result = scrape_book_sync(book_url)
            total += 1
            print(f"  [{total:>3}] {result}")

        nxt = soup.select_one("li.next a")
        page_url = urljoin(page_url, nxt.get("href")) if nxt else None
        pages += 1

    print(f"\nBitti. {pages} sayfa tarandı, {total} kitap işlendi.")
    print(f"Veritabanındaki toplam kitap: {count_books()}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=2, help="taranacak katalog sayfası sayısı")
    args = ap.parse_args()
    run(args.pages)

"""
DB testi: upsert_book aynı URL için duplicate satır AÇMAMALI (URL'e göre upsert).
İkinci kez aynı URL gelince mevcut satır güncellenir, sayı artmaz.
"""
from __future__ import annotations

from parser.extract import Book
from storage.db import count_books, upsert_book


def _book(url: str, title: str, price: float) -> Book:
    return Book(title=title, price=price, availability="In stock", rating=4, url=url)


def test_insert_then_count():
    assert count_books() == 0
    upsert_book(_book("https://x/1", "Kitap 1", 10.0))
    assert count_books() == 1


def test_upsert_same_url_no_duplicate():
    url = "https://books.toscrape.com/catalogue/dup_1/index.html"
    upsert_book(_book(url, "İlk Başlık", 10.0))
    upsert_book(_book(url, "İkinci Başlık", 99.9))   # aynı URL -> güncelle
    assert count_books() == 1                        # duplicate satır yok


def test_upsert_updates_fields():
    url = "https://books.toscrape.com/catalogue/upd_1/index.html"
    upsert_book(_book(url, "Eski", 10.0))
    upsert_book(_book(url, "Yeni", 42.5))

    from storage.db import BookRow, session_scope
    with session_scope() as s:
        row = s.query(BookRow).filter_by(url=url).one()
        assert row.title == "Yeni"
        assert row.price == 42.5


def test_distinct_urls_create_rows():
    upsert_book(_book("https://x/a", "A", 1.0))
    upsert_book(_book("https://x/b", "B", 2.0))
    assert count_books() == 2

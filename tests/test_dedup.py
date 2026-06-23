"""
Dedup testi: ilk görüşte False (yeni -> işle), ikinci görüşte True (görüldü -> atla).

Paylaşılan global `dedup` örneğini kirletmemek için her test kendi Deduplicator()
örneğini kurar. Redis ulaşılamaz olduğundan (conftest) backend 'memory' olur; mantık
her iki backend'de de aynıdır.
"""
from __future__ import annotations

from core.dedup import Deduplicator


def test_backend_is_memory_without_redis():
    d = Deduplicator()
    assert d.backend == "memory"


def test_check_and_mark_first_false_second_true():
    d = Deduplicator()
    url = "https://books.toscrape.com/catalogue/some-book_1/index.html"
    assert d.check_and_mark(url) is False   # ilk görüş -> işle
    assert d.check_and_mark(url) is True    # ikinci görüş -> atla


def test_seen_reflects_mark():
    d = Deduplicator()
    url = "https://books.toscrape.com/catalogue/other-book_2/index.html"
    assert d.seen(url) is False
    d.mark(url)
    assert d.seen(url) is True


def test_distinct_urls_independent():
    d = Deduplicator()
    u1 = "https://books.toscrape.com/a"
    u2 = "https://books.toscrape.com/b"
    assert d.check_and_mark(u1) is False
    assert d.check_and_mark(u2) is False   # farklı URL etkilenmez
    assert d.check_and_mark(u1) is True
    assert d.check_and_mark(u2) is True


def test_key_normalizes_case_and_whitespace():
    from core.dedup import _key
    assert _key("  HTTPS://Books.Toscrape.com/X  ") == _key("https://books.toscrape.com/x")

"""
Adım 6 testi: retry tetikleyicisi + dead-letter yönlendirmesi.

Eager-mod autoretry durum makinesine bağlanmak yerine mekanizmayı parça parça,
deterministik test ediyoruz:
  1. fetch başarısızsa scrape_book FetchError fırlatır (autoretry'ı tetikleyen olay).
  2. retry'lar tükenip görev kalıcı başarısız olunca on_failure dead-letter'a yazar.
  3. push_dead_letter, redis yoksa loga düşer (patlamaz).
"""
from __future__ import annotations

import pytest

from core.dedup import Deduplicator
import workers.tasks as tasks


def test_scrape_book_raises_fetcherror_on_fetch_failure(monkeypatch):
    monkeypatch.setattr(tasks.fetcher, "get", lambda url: None)   # fetch hep başarısız
    monkeypatch.setattr(tasks, "dedup", Deduplicator())          # taze dedup
    with pytest.raises(tasks.FetchError):
        # .run() görev gövdesini Celery makinesi olmadan doğrudan çalıştırır.
        tasks.scrape_book.run("https://books.toscrape.com/catalogue/never-here.html")


def test_on_failure_routes_to_dead_letter(monkeypatch):
    captured: list[dict] = []
    monkeypatch.setattr(tasks, "push_dead_letter", lambda payload: captured.append(payload))

    url = "https://books.toscrape.com/catalogue/never-here.html"
    exc = tasks.FetchError(f"fetch failed: {url}")
    # Celery retry'lar tükenince bu handler'ı çağırır:
    tasks.scrape_book.on_failure(exc, "task-id-123", [url], {}, None)

    assert captured, "dead-letter'a yazılmalıydı"
    assert captured[0]["task"] == "workers.scrape_book"
    assert captured[0]["args"] == [url]
    assert "fetch failed" in captured[0]["error"]


def test_push_dead_letter_falls_back_to_log_without_redis(capsys, monkeypatch):
    monkeypatch.setattr(tasks.dedup, "_client", None, raising=False)
    tasks.push_dead_letter({"task": "x", "args": ["u"], "error": "boom"})
    out = capsys.readouterr().out
    assert "[dead-letter]" in out

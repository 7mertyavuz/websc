"""
discover_catalog batch/chunk testi.

Celery'yi EAGER moda alıp (broker/worker gerektirmez) fetcher'ı sahte HTML döndürecek
şekilde yamalıyoruz. Böylece ağ'a çıkmadan:
  - chunked modun beklenen sayıda chunk ürettiğini,
  - tüm kitapların pipeline'dan geçip DB'ye yazıldığını,
  - chunk_size<=1 iken geriye uyumlu per_url moduna düştüğünü
doğruluyoruz.
"""
from __future__ import annotations

import pytest

from core.dedup import Deduplicator
import core.dedup as dedup_mod
import workers.tasks as tasks
from workers.celery_app import celery_app
from storage.db import count_books


CATALOG = """
<html><body>
  <article class="product_pod"><h3><a href="book-1.html">B1</a></h3></article>
  <article class="product_pod"><h3><a href="book-2.html">B2</a></h3></article>
  <article class="product_pod"><h3><a href="book-3.html">B3</a></h3></article>
  <article class="product_pod"><h3><a href="book-4.html">B4</a></h3></article>
  <article class="product_pod"><h3><a href="book-5.html">B5</a></h3></article>
</body></html>
"""

def _book_html(n: str) -> str:
    return f"""
    <html><body>
      <div class="product_main"><h1>Kitap {n}</h1>
        <p class="price_color">£{n}.00</p>
        <p class="availability">In stock (3 available)</p>
        <p class="star-rating Three"></p>
      </div>
    </body></html>
    """


def _fake_get(url: str):
    if "page-" in url:
        return CATALOG
    # book-N.html -> N
    import re
    m = re.search(r"book-(\d+)", url)
    return _book_html(m.group(1)) if m else None


@pytest.fixture
def eager(monkeypatch):
    monkeypatch.setattr(celery_app.conf, "task_always_eager", True)
    monkeypatch.setattr(celery_app.conf, "task_eager_propagates", True)
    # fetcher'ı her iki referans noktasında da yamala.
    monkeypatch.setattr(tasks.fetcher, "get", _fake_get)
    # Her test taze dedup kullansın (global'i kirletme).
    monkeypatch.setattr(dedup_mod, "dedup", Deduplicator())
    monkeypatch.setattr(tasks, "dedup", dedup_mod.dedup)
    yield


def test_chunked_dispatch_processes_all_books(eager):
    res = tasks.discover_catalog.apply(args=[None, 1, 2]).get()
    assert res["mode"] == "chunked"
    assert res["books_dispatched"] == 5
    assert res["chunks"] == 3            # ceil(5/2)
    assert res["chunk_size"] == 2
    assert count_books() == 5            # hepsi DB'ye yazıldı


def test_backward_compatible_per_url(eager):
    res = tasks.discover_catalog.apply(args=[None, 1, 1]).get()
    assert res["mode"] == "per_url"      # chunk_size<=1 -> eski davranış
    assert res["books_dispatched"] == 5
    assert count_books() == 5

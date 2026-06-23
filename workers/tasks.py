"""
Worker görevleri = pipeline'ın çalışan kalbi.

Akış (senin 6 adımlık senaryonun bypass'sız hali):
  1. discover_catalog : katalog sayfalarını gezip kitap URL'lerini bulur
  2. scrape_book      : tek bir kitap URL'ini -> dedup -> fetch -> parse -> DB

Her kitap URL'i ayrı bir Celery görevi olur; 50 worker varsa 50 kitap aynı anda işlenir.
"""
from __future__ import annotations
import json
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from celery import shared_task, Task

from core.config import settings
from core.dedup import dedup
from core.fetcher import fetcher
from parser.extract import parse
from storage.db import init_db, upsert_book

init_db()


# ----------------------------------------------------------------------------
# Dead-letter + retry altyapısı
# ----------------------------------------------------------------------------
DEAD_LETTER_KEY = "scrapehub:dead_letter"


class FetchError(Exception):
    """Sayfa çekilemedi -> Celery'nin autoretry mekanizmasını tetiklemek için fırlatılır."""


def push_dead_letter(payload: dict) -> None:
    """
    Kalıcı olarak başarısız olan görevi 'dead-letter' kuyruğuna (redis listesi) yaz.
    Redis yoksa loga düş. Operatör buradan başarısızları inceleyip elle yeniden işleyebilir.
    """
    data = json.dumps(payload, ensure_ascii=False)
    client = getattr(dedup, "_client", None)
    if client is not None:
        try:
            client.rpush(DEAD_LETTER_KEY, data)
            return
        except Exception:
            pass
    print(f"[dead-letter] {data}")


class DeadLetterTask(Task):
    """Tüm retry'lar tükenip görev kalıcı başarısız olunca dead-letter'a yazar."""

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
    autoretry_for=(FetchError,),     # geçici çekim hatasında otomatik yeniden dene
    retry_backoff=True,              # üstel artan bekleme (1,2,4...s)
    retry_jitter=True,               # gürültü ekle (thundering herd'i önle)
    max_retries=None,                # aşağıda settings'ten gelir
    retry_kwargs={"max_retries": settings.max_retries},
)
def scrape_book(self, url: str) -> dict:
    """
    Tek kitabı işle.

    İki mod:
      - Klasik (default): URL-bazlı bloom dedup. Daha önce görüldüyse fetch bile etmeden atla.
      - Incremental (settings.incremental=True): URL görülmüş olsa bile sayfayı çek,
        İÇERİK değişmediyse atla, değiştiyse yeniden işle. Böylece fiyat/stok güncellemeleri
        yakalanır ama değişmeyen sayfalar boşuna parse/DB yazımı yapmaz.

    Dayanıklılık: fetch başarısızsa FetchError fırlatılır -> Celery üstel backoff ile
    `max_retries` kez yeniden dener; hepsi tükenirse DeadLetterTask.on_failure görevi
    dead-letter kuyruğuna (scrapehub:dead_letter) yazar.
    """
    if settings.incremental:
        # Incremental: içerik karşılaştırması için önce çekmemiz gerekir.
        html = fetcher.get(url)
        if not html:
            raise FetchError(f"fetch failed (incremental): {url}")
        if not dedup.content_changed(url, html):
            dedup.mark(url)
            return {"url": url, "status": "skipped_unchanged"}
        book = parse(html, url)
        if not book:
            return {"url": url, "status": "parse_failed"}
        upsert_book(book)
        dedup.mark(url)
        return {"url": url, "status": "updated", "title": book.title, "price": book.price}

    # Klasik mod (default davranış).
    # 1. Dedup: son 24 saatte çektiysek atla (bütçe/zaman tasarrufu).
    if dedup.check_and_mark(url):
        return {"url": url, "status": "skipped_duplicate"}

    # 2. Fetch (nazik, retry'lı). Başarısızsa FetchError -> autoretry -> (tükenirse) dead-letter.
    html = fetcher.get(url)
    if not html:
        raise FetchError(f"fetch failed: {url}")

    # 3. Parse.
    book = parse(html, url)
    if not book:
        return {"url": url, "status": "parse_failed"}

    # 4. Kaydet.
    upsert_book(book)
    return {"url": url, "status": "ok", "title": book.title, "price": book.price}


@shared_task(bind=True, name="workers.discover_catalog")
def discover_catalog(
    self,
    start_url: str | None = None,
    max_pages: int = 5,
    chunk_size: int = 10,
) -> dict:
    """
    Katalog sayfalarını gez, bulunan kitap URL'lerini scrape_book görevlerine dağıt.

    Ölçeklenme: URL'leri tek tek .delay() ile atmak yerine (binlerce URL'de broker'a
    binlerce ayrı mesaj = yük) Celery `chunks` ile GRUPLAR halinde atıyoruz. Her chunk
    görevi `chunk_size` kadar URL'i işler -> daha az mesaj, daha iyi throughput.

    Geriye uyumluluk: chunk_size <= 1 ise eski davranış (her URL için ayrı .delay()).
    Böylece küçük demo akışı hiç değişmeden çalışmaya devam eder.
    """
    base = settings.base_url
    page_url = start_url or urljoin(base, "catalogue/page-1.html")
    pages_done = 0

    # 1) Önce tüm kitap URL'lerini topla (sayfaları gezerek).
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

    # 2) Dağıtım stratejisi.
    if chunk_size and chunk_size > 1 and book_urls:
        # Celery chunks: argüman demetlerini grupla, tek group olarak kuyruğa at.
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

    # 2b) Geriye uyumlu yol: her URL için ayrı görev.
    for u in book_urls:
        scrape_book.delay(u)
    return {
        "pages_scanned": pages_done,
        "books_dispatched": len(book_urls),
        "mode": "per_url",
        "chunk_size": chunk_size,
    }

"""
Canlı PostgreSQL doğrulama scripti (verify_bloom.py'nin DB muadili).

storage/db.py'ın gerçek bir Postgres'e karşı uçtan uca çalıştığını gösterir:
bağlan -> tablo oluştur -> kayıt yaz (upsert) -> oku -> idempotent upsert.

Kullanım (docker-compose'daki postgres ayaktayken):

    docker compose up -d postgres
    DATABASE_URL=postgresql+psycopg2://scrape:scrape@localhost:5432/scrapehub \
        python tests/verify_postgres.py

DATABASE_URL verilmezse compose'un default kimlik bilgilerine düşer. Bu bir
pytest testi DEĞİL (dosya adı verify_*); standalone çalışır, conftest'in zorladığı
SQLite izolasyonundan etkilenmez, böylece GERÇEK Postgres yolunu sınar.
"""
from __future__ import annotations
import os
import sys

# 1) Proje kökünü import yoluna ekle.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# 2) DATABASE_URL'i modüller import EDİLMEDEN önce ayarla (settings env'i import'ta okur).
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg2://scrape:scrape@localhost:5432/scrapehub",
)

from core.config import settings          # noqa: E402
from parser.extract import Book           # noqa: E402


def main() -> int:
    print(f"DATABASE_URL : {settings.database_url}")

    if not settings.database_url.startswith(("postgresql", "postgres")):
        print("\n[X] DATABASE_URL Postgres'e işaret etmiyor. Örn:")
        print("    DATABASE_URL=postgresql+psycopg2://scrape:scrape@localhost:5432/scrapehub")
        return 1

    try:
        from storage.db import (
            BookRow, Base, _engine, count_books, init_db, ping_db,
            session_scope, upsert_book,
        )
    except Exception as e:
        print(f"\n[X] storage.db import edilemedi (psycopg2 kurulu mu?): {e!r}")
        return 1

    failures: list[str] = []
    try:
        # Bağlantı.
        ping_db()
        print("bağlantı     : OK (SELECT 1)")

        # Temiz başla.
        Base.metadata.drop_all(_engine)
        init_db()
        print("tablo        : oluşturuldu (drop_all + create_all)")

        before = count_books()
        if before != 0:
            failures.append(f"temiz tablo beklenirken {before} kayıt var")

        # Yaz.
        url = "https://books.toscrape.com/catalogue/pg_verify/index.html"
        upsert_book(Book(title="PG Doğrulama", price=33.0, availability="In stock", rating=5, url=url))
        print("yazma        : upsert_book çağrıldı")

        # Oku.
        with session_scope() as s:
            row = s.query(BookRow).filter_by(url=url).one()
        ok_write = (row.title == "PG Doğrulama" and row.price == 33.0)
        print(f"okuma        -> title={row.title!r} price={row.price}   (beklenen: 'PG Doğrulama' / 33.0)")
        if not ok_write:
            failures.append("yazılan kayıt geri okunamadı / alanlar uyuşmadı")

        # Idempotent upsert (duplicate satır olmamalı).
        upsert_book(Book(title="PG Doğrulama v2", price=44.0, availability="In stock", rating=4, url=url))
        cnt = count_books()
        print(f"idempotent   -> count={cnt}   (beklenen: 1, duplicate yok)")
        if cnt != 1:
            failures.append(f"idempotent upsert beklenirken count={cnt}")

        # Temizlik.
        Base.metadata.drop_all(_engine)
        print("temizlik     : tablo düşürüldü")

    except Exception as e:
        failures.append(f"çalışma hatası: {e!r}")

    print("\n" + "=" * 50)
    if failures:
        print("SONUC: BASARISIZ")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("SONUC: BASARILI  Gercek PostgreSQL yolu dogrulandi.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

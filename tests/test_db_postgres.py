"""
Postgres entegrasyon testi.

storage/db.py'ın GERÇEK bir PostgreSQL'e karşı çalıştığını uçtan uca doğrular:
tabloyu oluştur -> kayıt yaz (upsert) -> oku -> idempotent upsert (duplicate yok).

Postgres erişilemezse (psycopg2 yok ya da sunucuya bağlanılamıyor) test otomatik
SKIP edilir; böylece sadece SQLite olan CI ortamı yeşil kalır. Çalıştırmak için:

    docker compose up -d postgres
    POSTGRES_TEST_URL=postgresql+psycopg2://scrape:scrape@localhost:5432/scrapehub pytest tests/test_db_postgres.py
"""
from __future__ import annotations
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# docker-compose'daki postgres servisinin default kimlik bilgileri.
POSTGRES_URL = os.getenv(
    "POSTGRES_TEST_URL",
    "postgresql+psycopg2://scrape:scrape@localhost:5432/scrapehub",
)


def _postgres_available(url: str) -> bool:
    """Bağlanmayı dene; psycopg2 yoksa veya sunucu kapalıysa False."""
    try:
        engine = create_engine(url, connect_args={"connect_timeout": 2})
        with engine.connect():
            pass
        engine.dispose()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _postgres_available(POSTGRES_URL),
    reason="PostgreSQL erişilemez (psycopg2 yok veya sunucu kapalı) — entegrasyon testi atlandı",
)


def test_storage_db_works_against_postgres(monkeypatch):
    import storage.db as db
    from parser.extract import Book

    # storage.db'nin global motorunu bu test için Postgres'e bağla (sonra geri alınır).
    engine = create_engine(POSTGRES_URL, future=True)
    Session = sessionmaker(bind=engine, future=True)
    monkeypatch.setattr(db, "_engine", engine)
    monkeypatch.setattr(db, "_Session", Session)

    # Temiz başla: tabloyu (varsa) düşür, yeniden oluştur.
    db.Base.metadata.drop_all(engine)
    db.init_db()

    try:
        assert db.count_books() == 0
        assert db.ping_db() is True

        url = "https://books.toscrape.com/catalogue/pg_integration/index.html"
        db.upsert_book(Book(title="PG Kitap", price=12.5, availability="In stock", rating=5, url=url))

        # Yaz -> oku doğrulaması.
        assert db.count_books() == 1
        with db.session_scope() as s:
            row = s.query(db.BookRow).filter_by(url=url).one()
            assert row.title == "PG Kitap"
            assert row.price == 12.5
            assert row.rating == 5

        # Aynı URL'e ikinci upsert: günceller, duplicate satır açmaz (unique index).
        db.upsert_book(Book(title="PG Kitap v2", price=20.0, availability="In stock", rating=4, url=url))
        assert db.count_books() == 1
        with db.session_scope() as s:
            row = s.query(db.BookRow).filter_by(url=url).one()
            assert row.title == "PG Kitap v2"
            assert row.price == 20.0
    finally:
        # Test verisini bırakma: tabloyu düşür, bağlantıyı kapat.
        db.Base.metadata.drop_all(engine)
        engine.dispose()

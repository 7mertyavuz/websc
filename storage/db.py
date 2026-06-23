"""
Depolama katmanı.

Senin planında PostgreSQL vardı; burada SQLAlchemy ile soyutluyoruz.
DATABASE_URL Postgres'e işaret ediyorsa Postgres, etmiyorsa SQLite kullanılır.
Böylece repoyu klonlayan kişi sıfır kurulumla (SQLite ile) çalıştırabilir,
prodüksiyonda tek satır env değiştirip Postgres'e geçebilir.
"""
from __future__ import annotations
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Column, Float, Integer, String, Text, create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

from core.config import settings
from parser.extract import Book

Base = declarative_base()


class BookRow(Base):
    __tablename__ = "books"
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(512), nullable=False)
    price = Column(Float, nullable=False, default=0.0)
    availability = Column(String(128))
    rating = Column(Integer, default=0)
    # url üzerinde tek bir UNIQUE index: hem aynı URL'in iki kez yazılmasını engeller
    # hem de upsert'teki "WHERE url = ?" aramasını indeksli/hızlı yapar (ix_books_url).
    url = Column(String(1024), nullable=False, unique=True, index=True)
    description = Column(Text, default="")


_engine = create_engine(settings.database_url, future=True)
_Session = sessionmaker(bind=_engine, future=True)


def init_db() -> None:
    Base.metadata.create_all(_engine)


@contextmanager
def session_scope() -> Iterator:
    s = _Session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def upsert_book(book: Book) -> None:
    """URL'e göre upsert: varsa güncelle, yoksa ekle."""
    with session_scope() as s:
        row = s.query(BookRow).filter_by(url=book.url).one_or_none()
        if row is None:
            row = BookRow(url=book.url)
            s.add(row)
        row.title = book.title
        row.price = book.price
        row.availability = book.availability
        row.rating = book.rating
        row.description = book.description


def count_books() -> int:
    with session_scope() as s:
        return s.query(BookRow).count()


def ping_db() -> bool:
    """DB'ye gerçekten bağlanılabiliyor mu? Basit bir 'SELECT 1' ile doğrula."""
    with _engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return True

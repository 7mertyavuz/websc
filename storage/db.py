"""
Depolama katmanı. PostgreSQL 'ON CONFLICT' (Race Condition Safe)
"""
from __future__ import annotations
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Column, Float, Integer, String, Text, create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.dialects.postgresql import insert

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
    """PostgreSQL ON CONFLICT ile gerçek ve Worker-Safe Upsert."""
    with session_scope() as s:
        stmt = insert(BookRow).values(
            title=book.title,
            price=book.price,
            availability=book.availability,
            rating=book.rating,
            url=book.url,
            description=book.description
        )
        
        stmt = stmt.on_conflict_do_update(
            index_elements=['url'],
            set_=dict(
                title=stmt.excluded.title,
                price=stmt.excluded.price,
                availability=stmt.excluded.availability,
                rating=stmt.excluded.rating,
                description=stmt.excluded.description
            )
        )
        s.execute(stmt)

def count_books() -> int:
    with session_scope() as s:
        return s.query(BookRow).count()

def ping_db() -> bool:
    with _engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return True

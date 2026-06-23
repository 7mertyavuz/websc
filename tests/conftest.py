"""
Pytest ortak kurulum (fixtures).
Artık SQLite yerine gerçek PostgreSQL veritabanı (Docker veya CI üzerindeki) kullanılır.
"""
from __future__ import annotations
import os
import sys

# 1) Proje kökünü import yoluna ekle.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# 2) Gerçek PostgreSQL'i hedef al (Eğer ortamda DATABASE_URL yoksa varsayılanı kullan)
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://scrape:scrape@localhost:5432/scrapehub")

# 3) Dedup'ı deterministik tut: ulaşılamaz bir Redis adresi -> memory fallback.
os.environ["REDIS_URL"] = "redis://127.0.0.1:6399/0"

import pytest  # noqa: E402

@pytest.fixture(autouse=True)
def _fresh_db():
    """Her testten önce tabloları sıfırla -> testler birbirini etkilemesin."""
    from storage.db import Base, _engine, init_db
    # Tüm tabloları sil ve baştan yarat
    Base.metadata.drop_all(_engine)
    init_db()
    yield

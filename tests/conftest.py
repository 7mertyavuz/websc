"""
Pytest ortak kurulum (fixtures).

Kritik: storage/db.py ve core/config.py import edilir edilmez env'den okuma yapar
(settings = Settings() modül seviyesinde). Bu yüzden testlerin İZOLE geçici bir SQLite
veritabanı ve garantili 'memory' dedup backend'i kullanması için ilgili env değişkenlerini
HER ŞEYDEN ÖNCE, proje modülleri import edilmeden burada ayarlıyoruz.
"""
from __future__ import annotations
import os
import sys
import tempfile

# 1) Proje kökünü import yoluna ekle.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# 2) İzole geçici SQLite DB (gerçek scrapehub.db'ye dokunma).
_DB_FD, _DB_PATH = tempfile.mkstemp(suffix=".db", prefix="scrapehub_test_")
os.close(_DB_FD)
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH.replace(os.sep, '/')}"

# 3) Dedup'ı deterministik tut: ulaşılamaz bir Redis adresi -> ping başarısız -> memory fallback.
#    (Testler gerçek Redis gerektirmesin; bağlantı denemesi anında reddedilir.)
os.environ["REDIS_URL"] = "redis://127.0.0.1:6399/0"

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_db():
    """Her testten önce tabloları sıfırla -> testler birbirini etkilemesin."""
    from storage.db import Base, _engine, init_db
    Base.metadata.drop_all(_engine)
    init_db()
    yield


def pytest_sessionfinish(session, exitstatus):
    """Test bitince geçici DB dosyasını temizle."""
    try:
        os.remove(_DB_PATH)
    except OSError:
        pass

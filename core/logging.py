"""
Merkezi, yapılandırılmış logging kurulumu.

Tüm modüller `print()` yerine buradan bir logger alır:

    from core.logging import get_logger
    logger = get_logger(__name__)
    logger.info("...")

Seviye `LOG_LEVEL` env'inden ayarlanır (default INFO). `LOG_FILE` verilirse
loglar hem konsola hem o dosyaya yazılır; verilmezse yalnızca konsola.

Kurulum bir kez (idempotent) yapılır: root logger'a handler eklenir, böylece
modül bazlı logger'lar aynı format ve hedefleri paylaşır. Tekrar import edilse
bile handler'lar çoğalmaz.
"""
from __future__ import annotations
import logging
import sys

from core.config import settings

_LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def _configure_root() -> None:
    """Root logger'ı bir kez kur (konsol + opsiyonel dosya). Idempotent."""
    global _configured
    if _configured:
        return

    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    # Konsol (stderr) handler'ı.
    console = logging.StreamHandler(stream=sys.stderr)
    console.setLevel(level)
    console.setFormatter(formatter)
    root.addHandler(console)

    # Opsiyonel dosya handler'ı.
    if settings.log_file:
        try:
            file_handler = logging.FileHandler(settings.log_file, encoding="utf-8")
            file_handler.setLevel(level)
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        except OSError:
            # Dosya açılamazsa sessizce sadece konsola devam et.
            root.warning("LOG_FILE açılamadı, yalnızca konsola yazılıyor: %s", settings.log_file)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """İsimlendirilmiş bir logger döndür (root bir kez kurulduktan sonra)."""
    _configure_root()
    return logging.getLogger(name)

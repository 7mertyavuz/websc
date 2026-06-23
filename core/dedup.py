"""
Katman 2: Tekilleştirme (Deduplication).

Senin orijinal planındaki Redis Bloom Filter mantığı birebir burada.
Amaç: bir URL son N saat içinde çekildiyse tekrar kuyruğa atma.

İki mod:
  1. Redis Stack varsa  -> gerçek RedisBloom (BF.ADD / BF.EXISTS) - O(1), RAM'de, devasa ölçekli.
  2. Redis yoksa        -> in-memory set fallback (tek makinede ders/test için yeterli).

Bloom filter neden? 500k URL'i bir SQL tablosunda "SELECT ... WHERE url=?" ile
kontrol etmek pahalı. Bloom filter nanosaniyede "kesinlikle yok" veya "muhtemelen var"
cevabı verir. False-positive oranı ayarlanabilir (default %0.1).
"""
from __future__ import annotations
import hashlib
import time
from typing import Optional

from core.config import settings

try:
    import redis  # type: ignore
    _redis_available = True
except ImportError:
    _redis_available = False


def _key(url: str) -> str:
    """URL'i normalize edip sabit uzunlukta bir anahtara çevirir."""
    return hashlib.sha1(url.strip().lower().encode()).hexdigest()


class Deduplicator:
    """URL daha önce işlendi mi? sorusunu cevaplar."""

    BLOOM_NAME = "scrapehub:seen_urls"

    CHASH_PREFIX = "scrapehub:chash:"

    def __init__(self) -> None:
        self._client: Optional["redis.Redis"] = None
        self._mem: set[str] = set()        # fallback
        self._mem_ttl: dict[str, float] = {}
        self._mem_chash: dict[str, str] = {}   # incremental: url-key -> content hash (fallback)
        self.backend = "memory"

        if _redis_available:
            try:
                self._client = redis.Redis.from_url(
                    settings.redis_url, decode_responses=True
                )
                self._client.ping()
                self._ensure_bloom()
                self.backend = "redis-bloom"
            except Exception:
                # Redis ayakta değilse sessizce memory moduna düş.
                self._client = None

    def _ensure_bloom(self) -> None:
        """RedisBloom filtresini bir kez reserve et (zaten varsa hatayı yut)."""
        try:
            self._client.execute_command(
                "BF.RESERVE",
                self.BLOOM_NAME,
                settings.bloom_error_rate,
                settings.bloom_capacity,
            )
        except Exception:
            pass  # zaten reserve edilmiş

    def seen(self, url: str) -> bool:
        """Bu URL daha önce görüldüyse True döner."""
        k = _key(url)
        if self._client is not None:
            try:
                return bool(self._client.execute_command("BF.EXISTS", self.BLOOM_NAME, k))
            except Exception:
                pass
        # memory fallback (TTL kontrollü)
        now = time.time()
        exp = self._mem_ttl.get(k)
        if exp and exp < now:
            self._mem.discard(k)
            self._mem_ttl.pop(k, None)
            return False
        return k in self._mem

    def mark(self, url: str) -> None:
        """URL'i 'görüldü' olarak işaretle."""
        k = _key(url)
        if self._client is not None:
            try:
                self._client.execute_command("BF.ADD", self.BLOOM_NAME, k)
                return
            except Exception:
                pass
        self._mem.add(k)
        self._mem_ttl[k] = time.time() + settings.dedup_ttl_sec

    def check_and_mark(self, url: str) -> bool:
        """
        Atomik: görülmediyse işaretle ve False döndür (=işle),
        görülmüşse True döndür (=atla).
        """
        if self.seen(url):
            return True
        self.mark(url)
        return False

    # --- Incremental (artımlı) güncelleme: içerik-hash karşılaştırma ---
    def content_changed(self, url: str, html: str) -> bool:
        """
        Sayfanın İÇERİĞİ son görülenden farklı mı?
          - Yeni URL ya da içerik değişmiş  -> True  (yeniden işle) + yeni hash'i sakla.
          - İçerik aynı                      -> False (atla).

        URL-bazlı bloom dedup "bu URL'i hiç gördük mü?" sorusuna bakar; bu metot ise
        "gördüğümüzden bu yana sayfa değişti mi?" sorusuna bakar (incremental güncelleme).
        """
        new_hash = hashlib.sha1(html.encode("utf-8", "ignore")).hexdigest()
        k = _key(url)

        if self._client is not None:
            try:
                rkey = self.CHASH_PREFIX + k
                prev = self._client.get(rkey)
                if prev == new_hash:
                    return False
                self._client.set(rkey, new_hash, ex=settings.content_hash_ttl_sec)
                return True
            except Exception:
                pass  # redis sorunlu -> memory'e düş

        prev = self._mem_chash.get(k)
        if prev == new_hash:
            return False
        self._mem_chash[k] = new_hash
        return True


# tek paylaşımlı örnek
dedup = Deduplicator()

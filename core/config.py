"""
Merkezi konfigürasyon.
Tüm pipeline buradan beslenir. Env değişkeni yoksa makul default'lar devreye girer
ki repoyu klonlayan kişi hiçbir şey ayarlamadan çalıştırabilsin.
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass
class Settings:
    # --- Hedef site ---
    # books.toscrape.com: scraping pratiği için açıkça yayınlanmış demo sitesi.
    # Anti-bot savunması yok, kullanım izni var. Mimariyi burada öğreniyoruz.
    base_url: str = os.getenv("SCRAPE_BASE_URL", "https://books.toscrape.com/")

    # --- Ağ / nezaket ayarları ---
    # Proxy şelalesi / stealth YOK. Bunun yerine "iyi vatandaş" scraping:
    request_delay_sec: float = float(os.getenv("REQUEST_DELAY", "0.5"))  # istekler arası bekleme (default)
    # Domain başına ayrı gecikme: bazı siteler daha hassas, bazıları daha toleranslı.
    # Format: "domain1:saniye,domain2:saniye"  ör. "books.toscrape.com:0.5,example.com:2.0"
    domain_delays_raw: str = os.getenv("DOMAIN_DELAYS", "")
    max_concurrency: int = int(os.getenv("MAX_CONCURRENCY", "4"))        # aynı anda max istek
    request_timeout: float = float(os.getenv("REQUEST_TIMEOUT", "20"))
    max_retries: int = int(os.getenv("MAX_RETRIES", "3"))
    user_agent: str = os.getenv(
        "USER_AGENT",
        "ScrapeHub-Educational/1.0 (+ders projesi; toscrape demo)",
    )
    respect_robots: bool = os.getenv("RESPECT_ROBOTS", "true").lower() == "true"

    # --- Redis (kuyruk + bloom filter) ---
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # --- Veritabanı ---
    # Postgres varsa onu kullan, yoksa lokal SQLite'a düş ki sıfır kurulumla çalışsın.
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///scrapehub.db")

    # --- Dedup ---
    dedup_ttl_sec: int = int(os.getenv("DEDUP_TTL", str(60 * 60 * 24)))  # 24 saat
    bloom_capacity: int = int(os.getenv("BLOOM_CAPACITY", "1000000"))
    bloom_error_rate: float = float(os.getenv("BLOOM_ERROR_RATE", "0.001"))

    # --- Incremental (artımlı) güncelleme ---
    # Açıkken: bir URL daha önce görülse bile, sayfa İÇERİĞİ değiştiyse yeniden işlenir
    # (içerik hash'i karşılaştırılır). Kapalıyken: klasik URL-bazlı bloom dedup (default).
    incremental: bool = os.getenv("INCREMENTAL", "false").lower() == "true"
    # İçerik hash'lerinin saklanma süresi (incremental mod, redis backend).
    content_hash_ttl_sec: int = int(os.getenv("CONTENT_HASH_TTL", str(60 * 60 * 24 * 7)))  # 7 gün

    # NOT: Eski LLM tabanlı parser kaldırıldı. parser/extract.py artık LLM'siz,
    # çok kademeli (JSON-LD/meta -> çoklu CSS -> regex) dayanıklı bir parser kullanır;
    # API anahtarı gerektirmez.

    def __post_init__(self) -> None:
        self.domain_delays: dict[str, float] = self._parse_domain_delays(self.domain_delays_raw)

    @staticmethod
    def _parse_domain_delays(raw: str) -> dict[str, float]:
        """ "a.com:0.5, b.com:2" -> {"a.com": 0.5, "b.com": 2.0} (hatalı parçaları atla). """
        result: dict[str, float] = {}
        for part in raw.split(","):
            part = part.strip()
            if not part or ":" not in part:
                continue
            domain, _, val = part.rpartition(":")
            domain = domain.strip().lower()
            try:
                result[domain] = float(val.strip())
            except ValueError:
                continue
        return result

    def request_delay_for(self, url: str) -> float:
        """URL'in domain'ine özel gecikme; tanımlı değilse genel default'a düşer."""
        host = (urlparse(url).hostname or "").lower()
        if host in self.domain_delays:
            return self.domain_delays[host]
        # www. öneki toleransı
        if host.startswith("www.") and host[4:] in self.domain_delays:
            return self.domain_delays[host[4:]]
        return self.request_delay_sec


settings = Settings()

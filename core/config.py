"""
Merkezi konfigürasyon.
Tüm pipeline buradan beslenir. Env değişkeni yoksa makul default'lar devreye girer
ki repoyu klonlayan kişi hiçbir şey ayarlamadan çalıştırabilsin.
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field


@dataclass
class Settings:
    # --- Hedef site ---
    # books.toscrape.com: scraping pratiği için açıkça yayınlanmış demo sitesi.
    # Anti-bot savunması yok, kullanım izni var. Mimariyi burada öğreniyoruz.
    base_url: str = os.getenv("SCRAPE_BASE_URL", "https://books.toscrape.com/")

    # --- Ağ / nezaket ayarları ---
    # Proxy şelalesi / stealth YOK. Bunun yerine "iyi vatandaş" scraping:
    request_delay_sec: float = float(os.getenv("REQUEST_DELAY", "0.5"))  # istekler arası bekleme
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

    # --- LLM parsing (opsiyonel) ---
    use_llm_parser: bool = os.getenv("USE_LLM_PARSER", "false").lower() == "true"


settings = Settings()

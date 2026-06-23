"""
Merkezi konfigürasyon.
"""
from __future__ import annotations
import os
from dataclasses import dataclass
from urllib.parse import urlparse

@dataclass
class Settings:
    base_url: str = os.getenv("SCRAPE_BASE_URL", "https://books.toscrape.com/")
    
    # --- Güvenlik ve Proxy ---
    api_key: str = os.getenv("API_KEY", "BENIM_GIZLI_SIFREM_123")
    proxy_tier_1: str = os.getenv("PROXY_TIER_1", "") 
    proxy_tier_2: str = os.getenv("PROXY_TIER_2", "") 

    request_delay_sec: float = float(os.getenv("REQUEST_DELAY", "0.5"))
    domain_delays_raw: str = os.getenv("DOMAIN_DELAYS", "")
    max_concurrency: int = int(os.getenv("MAX_CONCURRENCY", "4"))
    request_timeout: float = float(os.getenv("REQUEST_TIMEOUT", "20"))
    max_retries: int = int(os.getenv("MAX_RETRIES", "3"))
    user_agent: str = os.getenv("USER_AGENT", "ScrapeHub-Educational/1.0")
    respect_robots: bool = os.getenv("RESPECT_ROBOTS", "true").lower() == "true"

    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    log_file: str = os.getenv("LOG_FILE", "")

    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///scrapehub.db")

    dedup_ttl_sec: int = int(os.getenv("DEDUP_TTL", str(60 * 60 * 24)))
    bloom_capacity: int = int(os.getenv("BLOOM_CAPACITY", "1000000"))
    bloom_error_rate: float = float(os.getenv("BLOOM_ERROR_RATE", "0.001"))

    incremental: bool = os.getenv("INCREMENTAL", "false").lower() == "true"
    content_hash_ttl_sec: int = int(os.getenv("CONTENT_HASH_TTL", str(60 * 60 * 24 * 7)))

    def __post_init__(self) -> None:
        self.domain_delays: dict[str, float] = self._parse_domain_delays(self.domain_delays_raw)

    @staticmethod
    def _parse_domain_delays(raw: str) -> dict[str, float]:
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
        host = (urlparse(url).hostname or "").lower()
        if host in self.domain_delays:
            return self.domain_delays[host]
        if host.startswith("www.") and host[4:] in self.domain_delays:
            return self.domain_delays[host[4:]]
        return self.request_delay_sec

settings = Settings()

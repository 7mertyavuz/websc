"""
Katman 3 + 4: Ağ, Stealth Bypass ve Proxy Şelalesi (Waterfall).
"""
from __future__ import annotations
import time
import urllib.robotparser as robotparser
from functools import lru_cache
from typing import Optional
from urllib.parse import urljoin

from curl_cffi import requests

from core.config import settings
from core.logging import get_logger

logger = get_logger(__name__)

@lru_cache(maxsize=1)
def _robot_parser() -> robotparser.RobotFileParser:
    rp = robotparser.RobotFileParser()
    robots_url = urljoin(settings.base_url, "/robots.txt")
    try:
        rp.set_url(robots_url)
        rp.read()
    except Exception:
        pass
    return rp

def allowed_by_robots(url: str) -> bool:
    if not settings.respect_robots:
        return True
    try:
        return _robot_parser().can_fetch("*", url) # Stealth için wildcard
    except Exception:
        return True

class Fetcher:
    def get(self, url: str) -> Optional[str]:
        if not allowed_by_robots(url):
            logger.warning("[robots] izin yok, atlanıyor: %s", url)
            return None

        delay = settings.request_delay_for(url)
        last_err: Optional[Exception] = None

        # --- PROXY ŞELALESİ (WATERFALL) ---
        waterfall_tiers = [(None, "chrome120")] # Tier 0: Kendi IP'miz
        
        if settings.proxy_tier_1:
            waterfall_tiers.append((settings.proxy_tier_1, "chrome120"))
        if settings.proxy_tier_2:
            waterfall_tiers.append((settings.proxy_tier_2, "safari15_3"))

        current_tier_idx = 0

        for attempt in range(1, settings.max_retries + 1):
            current_proxy, impersonate_browser = waterfall_tiers[current_tier_idx]
            proxies = {"http": current_proxy, "https": current_proxy} if current_proxy else None

            try:
                resp = requests.get(
                    url,
                    impersonate=impersonate_browser,
                    proxies=proxies,
                    timeout=settings.request_timeout
                )
                time.sleep(delay)

                if resp.status_code == 200:
                    return resp.text

                # WAF Engeliyse proxy yükselt (403/429/503)
                if resp.status_code in (403, 429, 503):
                    logger.warning("[WAF Block] %s %s", resp.status_code, url)
                    if current_tier_idx < len(waterfall_tiers) - 1:
                        current_tier_idx += 1
                        logger.info("Proxy seviyesi artırıldı -> Tier %d", current_tier_idx)
                    else:
                        wait = delay * (2 ** attempt)
                        logger.warning("Tüm proxyler banlandı, %.1fs bekleniyor...", wait)
                        time.sleep(wait)
                    continue

                if 400 <= resp.status_code < 500:
                    logger.warning("[skip] %s %s", resp.status_code, url)
                    return None

            except requests.RequestsError as e:
                last_err = e
                # Ağ Hatası olursa da Proxy yükselt
                if current_tier_idx < len(waterfall_tiers) - 1:
                    current_tier_idx += 1
                    logger.info("Proxy Bağlantı Hatası -> Tier %d geçiliyor", current_tier_idx)
                else:
                    wait = delay * (2 ** attempt)
                    logger.warning("[retry %d/%d] Ağ Hatası -> %.1fs", attempt, settings.max_retries, wait)
                    time.sleep(wait)

        if last_err:
            logger.error("[fail] %s: %r", url, last_err)
        return None

    def close(self) -> None:
        pass

fetcher = Fetcher()

"""
Katman 3 + 4: Ağ ve İndirme.

Senin planında burası "proxy şelalesi + stealth tarayıcı + Datadome bypass" idi.
İzin veren bir hedefte (toscrape) bunların HİÇBİRİNE gerek yok. Onun yerine
sağlam mühendislik pratikleri koyuyoruz:

  - httpx ile basit, hızlı, async-uyumlu istekler
  - Üstel artan bekleme (exponential backoff) ile retry
  - İstekler arası nezaket gecikmesi (sunucuyu yormamak)
  - robots.txt kontrolü (izin verilen path mi?)

Bu, "scraping'i doğru yapmak" demek. Aynı retry/backoff/rate-limit mantığı
herhangi bir açık API ya da izin veren sitede de geçerli.
"""
from __future__ import annotations
import time
import urllib.robotparser as robotparser
from functools import lru_cache
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx

from core.config import settings


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
        return _robot_parser().can_fetch(settings.user_agent, url)
    except Exception:
        return True  # robots okunamazsa engelleme, ama nazik davran


class Fetcher:
    """Tek bir sayfayı nazikçe indiren retry'lı istemci."""

    def __init__(self) -> None:
        self._client = httpx.Client(
            headers={"User-Agent": settings.user_agent},
            timeout=settings.request_timeout,
            follow_redirects=True,
        )

    def get(self, url: str) -> Optional[str]:
        if not allowed_by_robots(url):
            print(f"[robots] izin yok, atlanıyor: {url}")
            return None

        last_err: Optional[Exception] = None
        for attempt in range(1, settings.max_retries + 1):
            try:
                resp = self._client.get(url)
                # Nezaket gecikmesi: her istekten sonra biraz bekle.
                time.sleep(settings.request_delay_sec)

                if resp.status_code == 200:
                    return resp.text
                # 429/503 -> sunucu "yavaşla" diyor, backoff ile saygı göster.
                if resp.status_code in (429, 503):
                    wait = settings.request_delay_sec * (2 ** attempt)
                    print(f"[backoff] {resp.status_code} -> {wait:.1f}s bekle ({url})")
                    time.sleep(wait)
                    continue
                # Diğer 4xx: tekrar denemeye değmez.
                if 400 <= resp.status_code < 500:
                    print(f"[skip] {resp.status_code} {url}")
                    return None
            except httpx.HTTPError as e:
                last_err = e
                wait = settings.request_delay_sec * (2 ** attempt)
                print(f"[retry {attempt}/{settings.max_retries}] {e!r} -> {wait:.1f}s")
                time.sleep(wait)

        if last_err:
            print(f"[fail] {url}: {last_err!r}")
        return None

    def close(self) -> None:
        self._client.close()


fetcher = Fetcher()

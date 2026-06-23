"""
Katman 5: Ayrıştırma (Parsing).

Senin planındaki "HTML -> Markdown -> Pydantic -> kusursuz JSON" fikri burada.
Senin CarAd modelinin toscrape karşılığı: Book.

İKİ parser sunuyoruz, ikisi de AYNI Pydantic modelini döndürür:
  1. parse_html()  -> klasik BeautifulSoup ile CSS seçici. Hızlı, ücretsiz, deterministik.
  2. parse_llm()   -> HTML'i sadeleştirip LLM'e verir, LLM Pydantic şemasına uygun JSON döndürür.
                      "Site tasarımı değişse de kod patlamasın" senaryosu için.

Ders için default CSS parser'dır (LLM API anahtarı gerektirmez).
USE_LLM_PARSER=true yaparsan LLM yoluna geçer.
"""
from __future__ import annotations
import re
from typing import Optional

from bs4 import BeautifulSoup
from pydantic import BaseModel, field_validator

from core.config import settings


# --- Senin CarAd modelinin muadili ---
class Book(BaseModel):
    title: str
    price: float
    availability: str
    rating: int          # 1-5 yıldız
    url: str
    description: str = ""

    @field_validator("rating")
    @classmethod
    def _rating_range(cls, v: int) -> int:
        return max(0, min(5, v))


_RATING_MAP = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}


def _clean_price(text: str) -> float:
    # "£51.77" -> 51.77 ; para birimi simgesi ve gürültüyü at.
    m = re.search(r"[\d]+\.[\d]+", text.replace(",", ""))
    return float(m.group()) if m else 0.0


def parse_html(html: str, url: str) -> Optional[Book]:
    """Klasik, deterministik CSS-seçici parser."""
    soup = BeautifulSoup(html, "html.parser")
    try:
        title = soup.select_one("div.product_main h1").get_text(strip=True)

        price_el = soup.select_one("p.price_color")
        price = _clean_price(price_el.get_text()) if price_el else 0.0

        avail_el = soup.select_one("p.availability")
        availability = avail_el.get_text(strip=True) if avail_el else "unknown"

        rating = 0
        star = soup.select_one("p.star-rating")
        if star:
            for cls in star.get("class", []):
                if cls in _RATING_MAP:
                    rating = _RATING_MAP[cls]
                    break

        desc_el = soup.select_one("#product_description ~ p")
        description = desc_el.get_text(strip=True) if desc_el else ""

        return Book(
            title=title,
            price=price,
            availability=availability,
            rating=rating,
            url=url,
            description=description,
        )
    except Exception as e:
        print(f"[parse] başarısız {url}: {e!r}")
        return None


def html_to_markdown(html: str) -> str:
    """LLM'e vermeden önce HTML'i sadeleştir (token tasarrufu)."""
    soup = BeautifulSoup(html, "html.parser")
    main = soup.select_one("div.product_main") or soup
    for tag in main(["script", "style"]):
        tag.decompose()
    return main.get_text("\n", strip=True)


def parse_llm(html: str, url: str) -> Optional[Book]:
    """
    LLM tabanlı parser. Site HTML'i değişse bile şemaya sadık JSON üretir.
    Burada Anthropic API kullanılabilir; anahtar yoksa CSS parser'a düşer.

    NOT: Gerçek çağrı kısmını yorumda bıraktım; anahtar/SDK kurunca açarsın.
    """
    try:
        import os
        import json
        import anthropic  # type: ignore

        if not os.getenv("ANTHROPIC_API_KEY"):
            return parse_html(html, url)

        client = anthropic.Anthropic()
        content = html_to_markdown(html)
        schema = Book.model_json_schema()

        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            messages=[{
                "role": "user",
                "content": (
                    "Aşağıdaki metinden kitap bilgisini çıkar. "
                    "SADECE şu JSON şemasına uygun, başka hiçbir şey olmadan JSON döndür.\n\n"
                    f"Şema: {json.dumps(schema)}\n\n"
                    f"URL: {url}\n\nMetin:\n{content[:4000]}"
                ),
            }],
        )
        raw = "".join(b.text for b in msg.content if b.type == "text")
        raw = raw.replace("```json", "").replace("```", "").strip()
        data = json.loads(raw)
        data["url"] = url
        return Book(**data)
    except Exception as e:
        print(f"[llm-parse] düştü, CSS parser'a geçiliyor: {e!r}")
        return parse_html(html, url)


def parse(html: str, url: str) -> Optional[Book]:
    """Konfigürasyona göre doğru parser'ı seçer."""
    if settings.use_llm_parser:
        return parse_llm(html, url)
    return parse_html(html, url)

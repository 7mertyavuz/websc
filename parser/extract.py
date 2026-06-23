"""
Katman 5: Ayrıştırma (Parsing) — LLM'siz, çok katmanlı dayanıklı çıkarım.

Tasarım felsefesi: "site tasarımı değişse de parser çalışmaya devam etsin, hiçbir API
anahtarı gerekmesin." Eskiden bir LLM parser'ı vardı; onu kaldırdık. Yerine her alan için
ÜÇ KADEMELİ bir fallback zinciri koyduk:

  1. Yapısal veri  : JSON-LD (<script type="application/ld+json">) ve og:/meta etiketleri.
                     Sayfanın görünümünden bağımsız, en sağlam kaynak.
  2. CSS seçiciler : Aynı alan için BİRDEN FAZLA yedek seçici. Biri kırılırsa diğeri yakalar.
  3. Regex/pattern : Son çare. Ham metinden desenle çek (ör. "£51.77", "22 available").

Her kademe Optional döndürür; ilk None-olmayan değer kazanır. Böylece tek bir seçici
değişse bile alan boş kalmaz. Pydantic Book modeli aynen korunur.
"""
from __future__ import annotations
import json
import re
from typing import Any, Callable, Optional

from bs4 import BeautifulSoup
from pydantic import BaseModel, field_validator


# --- Senin CarAd modelinin muadili (DEĞİŞMEDİ) ---
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


_RATING_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}


# ----------------------------------------------------------------------------
# Yardımcılar: yapısal veri kaynakları
# ----------------------------------------------------------------------------
def _load_jsonld(soup: BeautifulSoup) -> list[dict]:
    """Sayfadaki tüm JSON-LD bloklarını (schema.org) düz bir dict listesine indir."""
    out: list[dict] = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text() or ""
        try:
            data = json.loads(raw)
        except Exception:
            continue
        # JSON-LD tek obje, liste ya da @graph içinde olabilir.
        candidates = data if isinstance(data, list) else [data]
        for c in candidates:
            if isinstance(c, dict):
                if "@graph" in c and isinstance(c["@graph"], list):
                    out.extend(g for g in c["@graph"] if isinstance(g, dict))
                else:
                    out.append(c)
    return out


def _jsonld_get(jsonld: list[dict], *keys: str) -> Optional[Any]:
    """JSON-LD objelerinde verilen anahtarlardan ilk bulunanı döndür (iç içe destekli)."""
    for obj in jsonld:
        for key in keys:
            if "." in key:
                cur: Any = obj
                for part in key.split("."):
                    if isinstance(cur, list):
                        cur = cur[0] if cur else None
                    if not isinstance(cur, dict):
                        cur = None
                        break
                    cur = cur.get(part)
                if cur not in (None, ""):
                    return cur
            elif obj.get(key) not in (None, ""):
                return obj[key]
    return None


def _meta(soup: BeautifulSoup, *names: str) -> Optional[str]:
    """og:/meta etiketlerinden içerik çek (property veya name eşleşmesi)."""
    for n in names:
        tag = soup.find("meta", attrs={"property": n}) or soup.find("meta", attrs={"name": n})
        if tag and tag.get("content", "").strip():
            return tag["content"].strip()
    return None


def _css_text(soup: BeautifulSoup, *selectors: str) -> Optional[str]:
    """Sırayla CSS seçicileri dene; ilk metin bulunanı döndür."""
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            txt = el.get_text(strip=True)
            if txt:
                return txt
    return None


def _first(*chain: Callable[[], Optional[Any]]) -> Optional[Any]:
    """Fallback zincirini çalıştır: ilk None-olmayan (ve hata fırlatmayan) sonucu döndür."""
    for fn in chain:
        try:
            val = fn()
        except Exception:
            val = None
        if val not in (None, ""):
            return val
    return None


def _to_price(text: Any) -> Optional[float]:
    """'£51.77', '51,77 TL', 51.77 -> 51.77."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    s = str(text).replace(",", ".")
    m = re.search(r"\d+(?:\.\d+)?", s)
    return float(m.group()) if m else None


def _to_rating(text: Any) -> Optional[int]:
    """'Three', 'star-rating Three', '4', 4.0 -> int yıldız."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return int(round(float(text)))
    s = str(text).lower()
    for word, n in _RATING_WORDS.items():
        if word in s:
            return n
    m = re.search(r"\d+(?:\.\d+)?", s)
    return int(round(float(m.group()))) if m else None


# ----------------------------------------------------------------------------
# Alan bazlı çıkarım — her biri 3 kademeli fallback
# ----------------------------------------------------------------------------
def _extract_title(soup: BeautifulSoup, jsonld: list[dict]) -> Optional[str]:
    return _first(
        lambda: _jsonld_get(jsonld, "name", "headline"),                 # 1) yapısal
        lambda: _meta(soup, "og:title", "title"),
        lambda: _css_text(soup, "div.product_main h1", ".product_main h1",  # 2) CSS yedekleri
                          "article h1", "h1"),
        lambda: _title_from_tag(soup),                                   # 3) <title> fallback
    )


def _title_from_tag(soup: BeautifulSoup) -> Optional[str]:
    t = soup.find("title")
    if not t:
        return None
    # "Kitap Adı | Books to Scrape" -> "Kitap Adı"
    return re.split(r"\s*[|\-–]\s*", t.get_text(strip=True))[0] or None


def _extract_price(soup: BeautifulSoup, jsonld: list[dict]) -> float:
    val = _first(
        lambda: _to_price(_jsonld_get(jsonld, "offers.price", "price")),     # 1)
        lambda: _to_price(_meta(soup, "product:price:amount", "og:price:amount")),
        lambda: _to_price(_css_text(soup, "p.price_color", ".price_color",   # 2)
                                    ".price", "[class*=price]")),
        lambda: _to_price(_regex_price(soup)),                               # 3)
    )
    return float(val) if val is not None else 0.0


def _regex_price(soup: BeautifulSoup) -> Optional[str]:
    # Ham metinde para birimi simgesiyle birlikte fiyat ara.
    m = re.search(r"[£$€₺]\s?\d+(?:[.,]\d+)?", soup.get_text(" ", strip=True))
    return m.group() if m else None


def _extract_availability(soup: BeautifulSoup, jsonld: list[dict]) -> str:
    val = _first(
        lambda: _jsonld_get(jsonld, "offers.availability", "availability"),  # 1)
        lambda: _css_text(soup, "p.availability", "p.instock", ".availability",  # 2)
                          "[class*=availab]", "[class*=stock]"),
        lambda: _regex_availability(soup),                                   # 3)
    )
    if not val:
        return "unknown"
    # schema.org "http://schema.org/InStock" -> "InStock"
    return str(val).rsplit("/", 1)[-1].strip()


def _regex_availability(soup: BeautifulSoup) -> Optional[str]:
    txt = soup.get_text(" ", strip=True)
    m = re.search(r"(In stock(?:\s*\(\d+\s*available\))?|Out of stock|Stokta(?:\s*yok)?)",
                  txt, re.IGNORECASE)
    return m.group(1) if m else None


def _extract_rating(soup: BeautifulSoup, jsonld: list[dict]) -> int:
    val = _first(
        lambda: _to_rating(_jsonld_get(jsonld, "aggregateRating.ratingValue",  # 1)
                                       "ratingValue")),
        lambda: _to_rating(_rating_from_class(soup)),                          # 2)
        lambda: _to_rating(_meta(soup, "rating")),
        lambda: _to_rating(_regex_rating(soup)),                              # 3)
    )
    return int(val) if val is not None else 0


def _rating_from_class(soup: BeautifulSoup) -> Optional[str]:
    el = soup.select_one("p.star-rating") or soup.select_one("[class*=star-rating]")
    if el:
        return " ".join(el.get("class", []))
    return None


def _regex_rating(soup: BeautifulSoup) -> Optional[str]:
    m = re.search(r"(\d(?:\.\d)?)\s*(?:/|out of)\s*5", soup.get_text(" ", strip=True), re.I)
    return m.group(1) if m else None


def _extract_description(soup: BeautifulSoup, jsonld: list[dict]) -> str:
    val = _first(
        lambda: _jsonld_get(jsonld, "description"),                          # 1)
        lambda: _meta(soup, "og:description", "description"),
        lambda: _css_text(soup, "#product_description ~ p",                  # 2)
                          "#product_description + p", "div.product_main p"),
    )
    return str(val).strip() if val else ""


# ----------------------------------------------------------------------------
# Genel API (DEĞİŞMEDİ): parse_html() ve parse()
# ----------------------------------------------------------------------------
def parse_html(html: str, url: str) -> Optional[Book]:
    """
    LLM'siz, çok kademeli dayanıklı parser.
    Her alanı JSON-LD/meta -> çoklu CSS -> regex sırasıyla dener.
    Title bulunamazsa (sayfa tanınmıyor) None döner.
    """
    try:
        soup = BeautifulSoup(html, "html.parser")
        jsonld = _load_jsonld(soup)

        title = _extract_title(soup, jsonld)
        if not title:
            print(f"[parse] title bulunamadı, atlanıyor: {url}")
            return None

        return Book(
            title=title,
            price=_extract_price(soup, jsonld),
            availability=_extract_availability(soup, jsonld),
            rating=_extract_rating(soup, jsonld),
            url=url,
            description=_extract_description(soup, jsonld),
        )
    except Exception as e:
        print(f"[parse] başarısız {url}: {e!r}")
        return None


def parse(html: str, url: str) -> Optional[Book]:
    """Tek giriş noktası. Artık tek, dayanıklı, LLM'siz parser var."""
    return parse_html(html, url)

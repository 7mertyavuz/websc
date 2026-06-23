"""
Parser testi: parse_html() gerçek books.toscrape benzeri HTML'den doğru Pydantic
Book objesi çıkarıyor mu?

Aşağıdaki HTML, sitenin kitap detay sayfasının parser'ın kullandığı seçicileri
(div.product_main h1, p.price_color, p.availability, p.star-rating, #product_description ~ p)
içeren sadeleştirilmiş halidir.
"""
from __future__ import annotations

from parser.extract import Book, parse_html

SAMPLE_HTML = """
<html><body>
  <div class="col-sm-6 product_main">
    <h1>A Light in the Attic</h1>
    <p class="price_color">£51.77</p>
    <p class="instock availability">
      <i class="icon-ok"></i>
      In stock (22 available)
    </p>
    <p class="star-rating Three"><i class="icon-star"></i></p>
  </div>
  <div id="product_description" class="sub-header"><h2>Product Description</h2></div>
  <p>It's hard to imagine a world without A Light in the Attic. This classic poetry book is a treasure.</p>
</body></html>
"""

URL = "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"


def test_parse_html_returns_book():
    book = parse_html(SAMPLE_HTML, URL)
    assert book is not None
    assert isinstance(book, Book)


def test_parse_html_fields():
    book = parse_html(SAMPLE_HTML, URL)
    assert book.title == "A Light in the Attic"
    assert isinstance(book.price, float)
    assert book.price == 51.77
    assert "In stock" in book.availability
    assert isinstance(book.rating, int)
    assert book.rating == 3          # "Three" -> 3
    assert book.url == URL
    assert "A Light in the Attic" in book.description


def test_parse_html_rating_clamped():
    """field_validator rating'i 0-5 aralığına sıkıştırmalı."""
    b = Book(title="x", price=1.0, availability="ok", rating=9, url="u")
    assert b.rating == 5
    b2 = Book(title="x", price=1.0, availability="ok", rating=-3, url="u")
    assert b2.rating == 0


def test_parse_html_malformed_returns_none():
    """Beklenen yapı yoksa (h1/title/jsonld yok) parser çökmemeli, None dönmeli."""
    assert parse_html("<html><body>bos</body></html>", URL) is None


# --- Dayanıklılık: alternatif kaynaklar ---

JSONLD_HTML = """
<html><head>
<script type="application/ld+json">
{
  "@context": "https://schema.org", "@type": "Book",
  "name": "Schema Kitabı",
  "description": "JSON-LD'den gelen açıklama.",
  "aggregateRating": {"@type": "AggregateRating", "ratingValue": 4},
  "offers": {"@type": "Offer", "price": "33.50", "availability": "http://schema.org/InStock"}
}
</script>
</head><body><h1>Yanıltıcı Görsel Başlık</h1></body></html>
"""


def test_parse_prefers_jsonld_structured_data():
    """CSS seçiciler değişse/yanıltıcı olsa bile JSON-LD önce gelir."""
    book = parse_html(JSONLD_HTML, URL)
    assert book is not None
    assert book.title == "Schema Kitabı"
    assert book.price == 33.50
    assert book.rating == 4
    assert book.availability == "InStock"     # schema.org URL kuyruğundan sadeleşir
    assert book.description == "JSON-LD'den gelen açıklama."


OG_META_HTML = """
<html><head>
<meta property="og:title" content="Meta Başlık">
<meta property="og:description" content="Meta açıklama">
<meta property="product:price:amount" content="12.99">
</head><body>
<div class="brand-new-layout"><span class="cost">£12.99</span></div>
</body></html>
"""


def test_parse_falls_back_to_og_meta():
    """JSON-LD yoksa og:/meta etiketleri devreye girer (tasarım değişmiş site)."""
    book = parse_html(OG_META_HTML, URL)
    assert book is not None
    assert book.title == "Meta Başlık"
    assert book.price == 12.99
    assert book.description == "Meta açıklama"


REGEX_FALLBACK_HTML = """
<html><body>
<h1>Regex Kitabı</h1>
<div>Fiyat bilgisi: £7.25 — In stock (5 available). Rated 4 out of 5.</div>
</body></html>
"""


def test_parse_regex_last_resort():
    """Yapısal veri ve bilinen CSS seçiciler yoksa regex son çare olarak çalışır."""
    book = parse_html(REGEX_FALLBACK_HTML, URL)
    assert book is not None
    assert book.title == "Regex Kitabı"
    assert book.price == 7.25
    assert "In stock" in book.availability
    assert book.rating == 4

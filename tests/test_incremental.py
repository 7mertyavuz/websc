"""
Adım 5 testleri: domain-bazlı rate limit + içerik-hash incremental.
"""
from __future__ import annotations

from core.config import Settings
from core.dedup import Deduplicator


# --- Domain-bazlı request_delay ---

def test_request_delay_per_domain():
    s = Settings(domain_delays_raw="books.toscrape.com:0.5, example.com:2.0")
    assert s.request_delay_for("https://books.toscrape.com/catalogue/x.html") == 0.5
    assert s.request_delay_for("https://example.com/page") == 2.0


def test_request_delay_falls_back_to_default():
    s = Settings(domain_delays_raw="example.com:2.0")
    # Tanımsız domain -> genel default request_delay_sec
    assert s.request_delay_for("https://other-site.org/x") == s.request_delay_sec


def test_request_delay_www_tolerance():
    s = Settings(domain_delays_raw="example.com:2.0")
    assert s.request_delay_for("https://www.example.com/x") == 2.0


def test_domain_delays_ignores_malformed():
    s = Settings(domain_delays_raw="iyi.com:1.0, bozuk-parca, hatali:abc")
    assert s.domain_delays == {"iyi.com": 1.0}


# --- İçerik-hash incremental ---

def test_content_changed_new_then_same_then_changed():
    d = Deduplicator()
    url = "https://books.toscrape.com/catalogue/x.html"

    assert d.content_changed(url, "<html>v1</html>") is True    # yeni -> işle
    assert d.content_changed(url, "<html>v1</html>") is False   # aynı -> atla
    assert d.content_changed(url, "<html>v2 fiyat degisti</html>") is True  # değişti -> yeniden işle
    assert d.content_changed(url, "<html>v2 fiyat degisti</html>") is False # tekrar aynı -> atla


def test_content_changed_independent_per_url():
    d = Deduplicator()
    a = "https://books.toscrape.com/a"
    b = "https://books.toscrape.com/b"
    assert d.content_changed(a, "icerik-A") is True
    assert d.content_changed(b, "icerik-B") is True   # farklı URL bağımsız
    assert d.content_changed(a, "icerik-A") is False

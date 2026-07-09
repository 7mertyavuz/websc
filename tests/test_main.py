"""
API endpoint testleri.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from core.config import settings


@pytest.fixture
def client(monkeypatch):
    # Her testte yeni app import edilsin, global state karışmasın.
    from app.main import app
    return TestClient(app)


def test_root_serves_frontend_or_api_info(client):
    res = client.get("/")
    assert res.status_code == 200
    # frontend dizini varsa HTML döner, yoksa JSON mesaj döner.
    assert "ScrapeHub" in res.text or res.json().get("message", "").startswith("ScrapeHub")


def test_static_css_served(client):
    res = client.get("/static/styles.css")
    assert res.status_code == 200
    assert "stylesheet" not in res.text.lower()  # CSS dosyası, HTML değil


def test_stats_public(client):
    res = client.get("/stats")
    assert res.status_code == 200
    data = res.json()
    assert "books_in_db" in data
    assert "dedup_backend" in data


def test_books_pagination(client):
    res = client.get("/books?limit=10&offset=0")
    assert res.status_code == 200
    data = res.json()
    assert data["limit"] == 10
    assert data["offset"] == 0
    assert "books" in data
    assert "total" in data


def test_books_validation_rejects_negative_offset(client):
    res = client.get("/books?offset=-1")
    assert res.status_code == 422


def test_health_returns_json(client):
    res = client.get("/health")
    # Redis olmadan unhealthy (503) ya da tam ortamda healthy (200) olabilir.
    assert res.status_code in (200, 503)
    data = res.json()
    assert data["target"] == settings.base_url
    assert "checks" in data


def test_metrics_prometheus_format(client):
    res = client.get("/metrics")
    assert res.status_code == 200
    assert "scrapehub_" in res.text


def test_scrape_requires_api_key(client):
    res = client.post("/scrape", json={"max_pages": 1, "chunk_size": 1})
    assert res.status_code == 403


def test_scrape_one_requires_api_key(client):
    res = client.post("/scrape-one", json={"url": "http://example.com"})
    assert res.status_code == 403


def test_dead_letter_public(client):
    res = client.get("/dead-letter")
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    assert "count" in data

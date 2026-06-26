"""
Katman 1: Kuyruk yönetimi (Celery + Redis).
"""
from __future__ import annotations
from celery import Celery
from core.config import settings
from core.tracing import setup_tracing

# Worker için Dağıtık İzleme (Tracing) başlat
setup_tracing("scrapehub-worker")

from opentelemetry.instrumentation.celery import CeleryInstrumentor
CeleryInstrumentor().instrument()

celery_app = Celery(
    "scrapehub",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_default_retry_delay=5,
    task_max_retries=settings.max_retries,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_default_rate_limit=f"{settings.max_concurrency * 2}/s",
)

celery_app.autodiscover_tasks(["workers"])

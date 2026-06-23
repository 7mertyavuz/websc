"""
Katman 1: Kuyruk yönetimi (Celery + Redis).

FastAPI'den gelen "şu sayfaları kaz" emrini alır, worker'lara dağıtır.
Bir worker çökerse Celery görevi başka worker'a devreder (acks_late).

Redis ayakta değilse bile import patlamasın diye broker/backend lazy bağlanır;
worker başlatıldığında gerçek bağlantı kurulur.
"""
from __future__ import annotations
from celery import Celery

from core.config import settings

celery_app = Celery(
    "scrapehub",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_acks_late=True,                 # görev bitince onayla -> çökmede yeniden dene
    worker_prefetch_multiplier=1,        # adil dağıtım
    task_default_retry_delay=5,
    task_max_retries=settings.max_retries,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Aynı anda çok agresif olmamak için worker tarafı rate limit:
    task_default_rate_limit=f"{settings.max_concurrency * 2}/s",
)

# task'ların keşfedilmesi
celery_app.autodiscover_tasks(["workers"])

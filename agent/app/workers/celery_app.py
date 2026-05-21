from celery import Celery

from app.config import settings

celery_app = Celery(
    "agent",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    # Serialization
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Timezone
    timezone="UTC",
    enable_utc=True,
    # Reliability
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,  # one task at a time per worker (sandbox tasks are heavy)
    # Retries
    task_max_retries=3,
    task_default_retry_delay=30,
    # Results expire after 24h
    result_expires=86400,
)
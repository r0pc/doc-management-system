"""Celery application. One codebase, one image; queues split by pool.

The OCR queue must stay separate from `default` (AGENTS.md invariant): a
multi-minute OCR job on a shared pool starves every other pipeline stage.
"""

from celery import Celery

from app.config import Settings

settings = Settings()

celery_app = Celery(
    "docmgmt",
    broker=settings.redis_url,
    include=["app.workers.tasks"],
)
celery_app.set_default()
celery_app.set_current()

celery_app.conf.update(
    task_default_queue="default",
    # OCR-bound tasks route to the dedicated queue; everything else stays default.
    task_routes={
        "app.workers.tasks.ocr_*": {"queue": "ocr"},
        "app.workers.tasks.enqueue_ocr": {"queue": "ocr"},
    },
    # Pipeline stages are bounded jobs; a hung stage must not pin a worker slot.
    task_time_limit=300,
    task_soft_time_limit=240,
)

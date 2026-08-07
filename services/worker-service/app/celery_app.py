"""
Anything that shouldn't block a request/response cycle runs here instead: scraping job
boards, polling Gmail, generating embeddings. Redis is both the broker (task queue) and
the result backend — same instance the Gateway uses for caching/rate-limiting, just a
different logical use of it.
"""
import os

from celery import Celery

celery_app = Celery(
    "careerlens_worker",
    broker=os.getenv("REDIS_URL", "redis://redis:6379/0"),
    backend=os.getenv("REDIS_URL", "redis://redis:6379/0"),
    include=["app.tasks.scraping", "app.tasks.email_sync"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    beat_schedule={
        # Runs the job-board scrape every 6 hours without anyone triggering it manually —
        # this is what makes the pipeline's ingestion side genuinely autonomous instead
        # of "a script I remember to run."
        "scrape-job-boards-every-6h": {
            "task": "app.tasks.scraping.scrape_job_boards",
            "schedule": 6 * 60 * 60,
        },
    },
)

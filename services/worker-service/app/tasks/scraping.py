"""
This is the async trigger for pipeline/ingestion (see docs/DATA_ENGINEERING.md). The
worker's job is only to KICK OFF ingestion off the request/response path — the heavy
lifting (Spark ETL, MLlib) happens outside this service, orchestrated by Airflow
(pipeline/airflow/dags/job_pipeline_dag.py). Keeping this task thin means a slow scrape
never ties up a worker process that other background jobs also need.
"""
import logging

from app.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.scraping.scrape_job_boards")
def scrape_job_boards() -> dict:
    logger.info("scrape_job_boards: placeholder run — wire to pipeline/ingestion/job_apis.py")
    # Phase 2 (docs/ROADMAP.md): call pipeline/ingestion/job_apis.py's fetch functions,
    # write raw results to the landing zone, and publish a Kafka `new-posting-scraped`
    # event per new record so downstream consumers react immediately.
    return {"status": "not_yet_wired", "rows_ingested": 0}

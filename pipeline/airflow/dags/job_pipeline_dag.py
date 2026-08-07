"""
The one DAG that ties the whole batch side of the pipeline together on a schedule. Each
task below is a thin wrapper that shells out to a script you already have — the DAG's
job is sequencing and retries, not reimplementing logic. This is what lets you say "here's
the DAG" in an interview instead of "I ran some scripts in order."

Mounted into the Airflow containers at /opt/airflow/dags (see infra/docker-compose.yml,
bigdata profile) with the rest of pipeline/ mounted at /opt/airflow/pipeline.
"""
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

default_args = {
    "owner": "careerlens",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="job_pipeline",
    description="Ingest -> clean/aggregate (Spark) -> train (MLlib) -> load warehouse -> dbt",
    default_args=default_args,
    schedule_interval="@daily",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["careerlens", "data-engineering"],
) as dag:

    PIPELINE_DIR = "/opt/airflow/pipeline"

    ingest_real = BashOperator(
        task_id="ingest_real_job_postings",
        bash_command=f"python {PIPELINE_DIR}/ingestion/job_apis.py --out /opt/airflow/data/raw/real_postings.jsonl",
    )

    generate_synthetic = BashOperator(
        task_id="generate_synthetic_postings",
        bash_command=(
            f"python {PIPELINE_DIR}/ingestion/generate_synthetic_data.py "
            f"--rows 1000000 --out /opt/airflow/data/raw/synthetic_postings.jsonl"
        ),
    )

    spark_etl = BashOperator(
        task_id="spark_etl_clean_jobs",
        bash_command=(
            f"python {PIPELINE_DIR}/spark_jobs/etl_clean_jobs.py "
            f"--input /opt/airflow/data/raw/*.jsonl --output /opt/airflow/data/curated/postings.parquet"
        ),
    )

    mllib_train = BashOperator(
        task_id="train_salary_model",
        bash_command=(
            f"python {PIPELINE_DIR}/spark_jobs/mllib_salary_model.py "
            f"--input /opt/airflow/data/curated/postings.parquet"
        ),
    )

    dbt_run = BashOperator(
        task_id="dbt_run",
        bash_command=f"cd {PIPELINE_DIR}/dbt && dbt run",
    )

    dbt_test = BashOperator(
        task_id="dbt_test",
        bash_command=f"cd {PIPELINE_DIR}/dbt && dbt test",
    )

    # Fan-in: both ingestion sources feed the same ETL step; everything downstream is
    # strictly sequential because each step depends on the previous step's output.
    [ingest_real, generate_synthetic] >> spark_etl >> mllib_train >> dbt_run >> dbt_test

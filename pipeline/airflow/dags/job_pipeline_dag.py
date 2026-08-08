"""
The DAG that runs the whole batch pipeline on a schedule.

Each task shells out to a script that already exists and already works standalone — the
DAG's job is sequencing, retries and visibility, NOT reimplementing logic. Keeping the
scripts runnable on their own matters: you can debug one step directly instead of
through the scheduler, and this file stays readable.

Mounted into the Airflow containers at /opt/airflow/dags (infra/docker-compose.yml,
bigdata profile), with the rest of pipeline/ at /opt/airflow/pipeline.
"""
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

default_args = {
    "owner": "careerlens",
    # Retries matter here because two tasks call third-party APIs. Transient network
    # failures are normal, not exceptional, and a pipeline that dies on one blip isn't
    # production-shaped.
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "execution_timeout": timedelta(hours=1),
}

PIPELINE = "/opt/airflow/pipeline"
DATA = "/opt/airflow/data"
DB_URL = "postgresql://careerlens:change_me@postgres:5432/careerlens"

with DAG(
    dag_id="job_pipeline",
    description="ingest -> Spark ETL -> MLlib -> warehouse -> dbt models + tests",
    default_args=default_args,
    schedule="@daily",
    start_date=datetime(2026, 1, 1),
    catchup=False,  # don't backfill a year of runs the first time this is switched on
    max_active_runs=1,  # Spark jobs are memory-hungry; never run two at once
    tags=["careerlens", "data-engineering"],
) as dag:

    ingest_real = BashOperator(
        task_id="ingest_real_postings",
        bash_command=(
            f"python {PIPELINE}/ingestion/job_apis.py "
            f"--out {DATA}/raw/real_postings.jsonl "
            f'--terms "Data Engineer,Analytics Engineer,Machine Learning Engineer" '
            f"--countries in,us"
        ),
    )

    generate_synthetic = BashOperator(
        task_id="generate_synthetic_postings",
        bash_command=(
            f"python {PIPELINE}/ingestion/generate_synthetic_data.py "
            f"--rows 200000 --out {DATA}/raw/synthetic_postings.jsonl"
        ),
    )

    spark_etl = BashOperator(
        task_id="spark_etl",
        bash_command=(
            f"python {PIPELINE}/spark_jobs/etl_clean_jobs.py "
            f'--input "{DATA}/raw/*.jsonl" --output {DATA}/curated/postings.parquet'
        ),
    )

    train_model = BashOperator(
        task_id="train_salary_model",
        bash_command=(
            f"python {PIPELINE}/spark_jobs/mllib_salary_model.py "
            f"--input {DATA}/curated/postings.parquet "
            f"--model-out {DATA}/models/salary_gbt --metrics-out {DATA}/model_metrics.json"
        ),
    )

    load_warehouse = BashOperator(
        task_id="load_warehouse",
        bash_command=(
            f"python {PIPELINE}/ingestion/load_to_warehouse.py "
            f'--curated-dir {DATA}/curated --database-url "{DB_URL}"'
        ),
    )

    dbt_run = BashOperator(task_id="dbt_run", bash_command=f"cd {PIPELINE}/dbt && dbt run")

    # dbt test runs AFTER the models are built and is the pipeline's quality gate: if the
    # warehouse data is wrong, the run goes red here rather than silently serving bad
    # numbers to the dashboard.
    dbt_test = BashOperator(task_id="dbt_test", bash_command=f"cd {PIPELINE}/dbt && dbt test")

    # Both ingestion sources feed the same ETL (fan-in); everything after is sequential
    # because each step consumes the previous step's output.
    [ingest_real, generate_synthetic] >> spark_etl >> train_model >> load_warehouse >> dbt_run >> dbt_test

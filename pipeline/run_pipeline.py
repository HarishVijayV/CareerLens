"""
Run the whole batch pipeline in one command, without Airflow.

Airflow is the right tool for scheduled production runs, but it's heavy to spin up just
to iterate on a transform. This script runs the exact same steps in the exact same order
against your local machine, so the fast feedback loop stays fast. The Airflow DAG
(airflow/dags/job_pipeline_dag.py) calls these same scripts — neither duplicates logic.

Usage:
    python run_pipeline.py                    # full run, 200k synthetic rows
    python run_pipeline.py --rows 1000000     # scale up
    python run_pipeline.py --skip-real        # offline / no job-board APIs
    python run_pipeline.py --only spark,dbt   # re-run just some steps
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
DEFAULT_DB = "postgresql://careerlens:change_me@localhost:5432/careerlens"

SNOWFLAKE_VARS = ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD")


def resolve_dbt_target(requested: str | None) -> str:
    """Pick the dbt target: Snowflake if it's configured, Postgres otherwise.

    Both targets run the SAME models and the SAME tests — only the warehouse changes.
    That's the actual value of writing transformations in dbt rather than engine-specific
    scripts, and it's why the Snowflake trial expiring costs you nothing: the pipeline
    keeps running on Postgres without a single file changing.
    """
    if requested:
        return requested

    if all(os.getenv(var) for var in SNOWFLAKE_VARS):
        print("Snowflake credentials detected -> dbt target 'warehouse'")
        return "warehouse"

    print("No Snowflake credentials -> dbt target 'dev' (Postgres). See docs/CREDENTIALS.md.")
    return "dev"


def run_step(name: str, command: list[str], cwd: Path | None = None) -> float:
    print(f"\n{'=' * 70}\n  {name}\n{'=' * 70}")
    start = time.perf_counter()

    result = subprocess.run(command, cwd=cwd or HERE)
    elapsed = time.perf_counter() - start

    if result.returncode != 0:
        print(f"\nFAILED: {name} (exit {result.returncode}) after {elapsed:.1f}s")
        sys.exit(result.returncode)

    print(f"\nOK: {name} ({elapsed:.1f}s)")
    return elapsed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=200_000)
    parser.add_argument("--database-url", default=DEFAULT_DB)
    parser.add_argument("--skip-real", action="store_true", help="skip the live job-board APIs")
    parser.add_argument("--benchmark", action="store_true", help="also run the MapReduce comparison")
    parser.add_argument(
        "--only",
        default="",
        help="comma-separated subset: generate,real,spark,mllib,load,dbt,benchmark",
    )
    parser.add_argument(
        "--target",
        default=None,
        choices=["dev", "warehouse"],
        help="dbt target: dev=Postgres, warehouse=Snowflake. Auto-detected if omitted.",
    )
    args = parser.parse_args()

    only = {s.strip() for s in args.only.split(",") if s.strip()}

    def should(step: str) -> bool:
        return not only or step in only

    py = sys.executable
    timings: dict[str, float] = {}

    if should("generate"):
        timings["generate"] = run_step(
            f"1. Generate {args.rows:,} synthetic postings",
            [py, "ingestion/generate_synthetic_data.py", "--rows", str(args.rows),
             "--out", "data/raw/synthetic_postings.jsonl"],
        )

    if should("real") and not args.skip_real:
        timings["real"] = run_step(
            "2. Fetch real postings from job-board APIs",
            [py, "ingestion/job_apis.py", "--out", "data/raw/real_postings.jsonl",
             "--terms", "Data Engineer,Analytics Engineer,Machine Learning Engineer",
             "--countries", "in,us"],
        )

    if should("spark"):
        timings["spark_etl"] = run_step(
            "3. Spark ETL — clean, dedupe, aggregate",
            # glob so BOTH raw sources feed one ETL run; Spark reads a pattern natively
            [py, "spark_jobs/etl_clean_jobs.py", "--input", "data/raw/*.jsonl",
             "--output", "data/curated/postings.parquet"],
        )

    if should("mllib"):
        timings["mllib"] = run_step(
            "4. Train Spark MLlib salary model",
            [py, "spark_jobs/mllib_salary_model.py", "--input", "data/curated/postings.parquet"],
        )

    if should("load"):
        timings["load"] = run_step(
            "5. Load curated data into Postgres",
            [py, "ingestion/load_to_warehouse.py", "--curated-dir", "data/curated",
             "--database-url", args.database_url],
        )

    if should("dbt"):
        target = resolve_dbt_target(args.target)
        timings["dbt_run"] = run_step(
            f"6. dbt run — build the star schema (target: {target})",
            ["dbt", "run", "--target", target], cwd=HERE / "dbt",
        )
        timings["dbt_test"] = run_step(
            f"7. dbt test — data quality gate (target: {target})",
            ["dbt", "test", "--target", target], cwd=HERE / "dbt",
        )

    if args.benchmark or "benchmark" in only:
        timings["benchmark"] = run_step(
            "8. MapReduce vs Spark benchmark",
            [py, "mapreduce_demo/benchmark_compare.py",
             "--input", "data/raw/synthetic_postings.jsonl", "--runs", "3"],
        )

    print(f"\n{'=' * 70}\n  PIPELINE COMPLETE\n{'=' * 70}")
    for step, seconds in timings.items():
        print(f"  {step:<14} {seconds:>7.1f}s")
    print(f"  {'TOTAL':<14} {sum(timings.values()):>7.1f}s")
    print("\nNext: open http://localhost:3000/analytics to see the results.")


if __name__ == "__main__":
    main()

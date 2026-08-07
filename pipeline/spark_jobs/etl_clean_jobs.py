"""
The main PySpark ETL job — reads raw JSONL (from HDFS in the full setup, or a local path
for quick iteration), cleans it, and writes curated Parquet. See docs/DATA_ENGINEERING.md
for why each step exists.

Why Spark and not pandas: this is written so it scales past what fits in one machine's
RAM — Spark partitions the data across executors and only pulls small aggregated results
back to the driver (see the .show()/.write() calls, never a blanket .collect()). A pandas
version would need to load the whole file into one process's memory first.

Usage (local):
    python etl_clean_jobs.py --input data/raw/postings.jsonl --output data/curated/postings.parquet

Usage (against HDFS, once the bigdata profile is running):
    python etl_clean_jobs.py --input hdfs://namenode:9000/raw/postings.jsonl \
        --output hdfs://namenode:9000/curated/postings.parquet
"""
import argparse
import re

from pyspark.sql import SparkSession, functions as F
from pyspark.sql.types import IntegerType


def clean_salary_udf():
    """Salary sometimes arrives as an int, sometimes "$123,456/yr", sometimes null.
    Normalizing it here, once, is what lets every downstream consumer (dashboards,
    MLlib model, agents) assume a clean integer column instead of re-deriving this
    logic five times."""

    def _clean(value):
        if value is None:
            return None
        if isinstance(value, int):
            return value
        digits = re.sub(r"[^\d]", "", str(value))
        return int(digits) if digits else None

    return F.udf(_clean, IntegerType())


def build_spark(app_name: str = "careerlens-etl") -> SparkSession:
    return (
        SparkSession.builder.appName(app_name)
        # local[*] uses all cores on this machine — swap for a real cluster master URL
        # (e.g. yarn, or an EMR/Databricks endpoint) with zero code changes elsewhere.
        .master("local[*]")
        .config("spark.driver.memory", "4g")
        .getOrCreate()
    )


def run(input_path: str, output_path: str) -> None:
    spark = build_spark()
    clean_salary = clean_salary_udf()

    raw = spark.read.json(input_path)
    print(f"Raw rows read: {raw.count():,}")

    cleaned = (
        raw
        # dedup: the generator deliberately injects ~2% exact-duplicate postings —
        # dropDuplicates on posting_id is the fix. Real scraped data gets duplicates
        # from re-posted listings for the same reason.
        .dropDuplicates(["posting_id"])
        .withColumn("salary_clean", clean_salary(F.col("salary")))
        .withColumn("title", F.trim(F.col("title")))
        .filter(F.col("title").isNotNull())
    )

    print(f"Rows after cleaning/dedup: {cleaned.count():,}")

    # --- aggregations the dashboards/agents will query ---
    skill_demand = (
        cleaned.select(F.explode("required_skills").alias("skill"))
        .groupBy("skill")
        .count()
        .orderBy(F.desc("count"))
    )
    print("Top 10 in-demand skills:")
    skill_demand.show(10)

    salary_by_seniority = cleaned.groupBy("seniority").agg(
        F.avg("salary_clean").alias("avg_salary"), F.count("*").alias("postings")
    )
    salary_by_seniority.show()

    cleaned.write.mode("overwrite").parquet(output_path)
    skill_demand.write.mode("overwrite").parquet(output_path.replace(".parquet", "_skill_demand.parquet"))
    print(f"Curated data written -> {output_path}")

    spark.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    run(args.input, args.output)

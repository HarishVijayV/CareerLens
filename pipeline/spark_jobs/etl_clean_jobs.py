"""
The main PySpark ETL job — reads raw JSONL, cleans it, and writes curated Parquet plus
the aggregate tables the app and dashboards read. See docs/DATA_ENGINEERING.md for the
"why" behind each step.

Why Spark and not pandas: this is written to scale past what fits in one machine's RAM.
Spark partitions the work across executors and only ever brings small aggregated results
back to the driver — note there is no blanket .collect() anywhere in this file.

Usage (local):
    python spark_jobs/etl_clean_jobs.py --input data/raw/postings.jsonl \
        --output data/curated/postings.parquet

Usage (against HDFS, with the bigdata compose profile running):
    python spark_jobs/etl_clean_jobs.py --input hdfs://localhost:9000/raw/postings.jsonl \
        --output hdfs://localhost:9000/curated/postings.parquet
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from pyspark.sql import functions as F  # noqa: E402

from spark_common import build_spark  # noqa: E402


def clean_salary(column: str = "salary"):
    """Salary arrives as an int, or "$123,456/yr", or null, depending on the source.

    Deliberately native Spark SQL (regexp_replace + cast) rather than a Python UDF: a
    UDF would force every row to be serialized out of the JVM into a Python worker and
    back, which is dramatically slower and adds a whole class of failure modes. Native
    expressions compile into Spark's engine and stay in the JVM. "Avoid Python UDFs when
    a native expression exists" is one of the highest-value Spark lessons there is.
    """
    digits_only = F.regexp_replace(F.col(column).cast("string"), r"[^0-9]", "")
    return F.when(digits_only == "", None).otherwise(digits_only.cast("long"))


def run(input_path: str, output_path: str) -> None:
    spark = build_spark("careerlens-etl")

    raw = spark.read.json(input_path)
    raw_count = raw.count()
    print(f"Raw rows read: {raw_count:,}")

    cleaned = (
        raw
        # The generator injects ~2% exact-duplicate postings on purpose, and real
        # scraped feeds duplicate for their own reasons (re-posted listings). Either
        # way, dedup on the natural key is the fix.
        .dropDuplicates(["posting_id"])
        .withColumn("salary_clean", clean_salary())
        .withColumn("title", F.trim(F.col("title")))
        .filter(F.col("title").isNotNull())
    )

    # Cache: `cleaned` is consumed several times below (count + 3 aggregations + write).
    # Without this, Spark would recompute the whole read+clean lineage for each one —
    # this single line is often the difference between a slow job and a fast one.
    cleaned.cache()

    clean_count = cleaned.count()
    print(f"Rows after cleaning/dedup: {clean_count:,}  (removed {raw_count - clean_count:,})")

    # ---- aggregate tables the app + dashboards read ----
    skill_demand = (
        cleaned.select(F.explode("required_skills").alias("skill"))
        .groupBy("skill")
        .count()
        .orderBy(F.desc("count"))
    )
    print("\nTop 10 in-demand skills:")
    skill_demand.show(10, truncate=False)

    salary_by_seniority = (
        cleaned.groupBy("seniority")
        .agg(
            F.round(F.avg("salary_clean")).alias("avg_salary"),
            F.expr("percentile_approx(salary_clean, 0.5)").alias("median_salary"),
            F.count("*").alias("postings"),
        )
        .orderBy("seniority")
    )
    print("Salary by seniority:")
    salary_by_seniority.show(truncate=False)

    postings_by_month = cleaned.groupBy("posted_month").count().orderBy("posted_month")
    print("Postings by month (seasonality):")
    postings_by_month.show(12, truncate=False)

    salary_by_region = (
        cleaned.groupBy("region")
        .agg(F.round(F.avg("salary_clean")).alias("avg_salary"), F.count("*").alias("postings"))
        .orderBy(F.desc("avg_salary"))
    )
    print("Salary by region:")
    salary_by_region.show(truncate=False)

    # ---- write curated outputs ----
    out = Path(output_path)
    base = str(out.with_suffix(""))

    # Bridge table: one row per (posting, skill). A posting has many skills and a skill
    # belongs to many postings — the textbook many-to-many, and the textbook fix is a
    # bridge table rather than an array column. It also sidesteps a real portability
    # problem: array types differ across engines (Postgres `text[]` + unnest vs
    # Snowflake VARIANT + FLATTEN), whereas a bridge table is plain rows that every
    # warehouse and every dbt adapter handles identically.
    posting_skills = cleaned.select(
        "posting_id", F.explode("required_skills").alias("skill")
    )
    posting_skills.write.mode("overwrite").parquet(f"{base}_posting_skills.parquet")

    cleaned.drop("required_skills").write.mode("overwrite").parquet(output_path)
    skill_demand.write.mode("overwrite").parquet(f"{base}_skill_demand.parquet")
    salary_by_seniority.write.mode("overwrite").parquet(f"{base}_salary_by_seniority.parquet")
    postings_by_month.write.mode("overwrite").parquet(f"{base}_postings_by_month.parquet")
    salary_by_region.write.mode("overwrite").parquet(f"{base}_salary_by_region.parquet")

    print(f"\nCurated data written -> {output_path} (+ 4 aggregate tables)")

    cleaned.unpersist()
    spark.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    run(args.input, args.output)

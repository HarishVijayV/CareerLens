"""
Runs the SAME aggregation (skill-frequency count) two ways on the same input and times
both, so you get your own real numbers for the "X% faster with Spark" claim instead of
inheriting the number from your old resume line. See docs/DATA_ENGINEERING.md for why
the difference exists (disk-based shuffle between every stage vs. Spark's in-memory DAG).

Usage:
    python benchmark_compare.py --input data/raw/postings.jsonl
"""
import argparse
import subprocess
import time
from pathlib import Path


def run_mapreduce_style(input_path: Path) -> float:
    """mapper.py | sort | reducer.py — `sort` is doing real disk-backed work for large
    inputs, which is exactly the stage that mirrors Hadoop's shuffle-to-disk behavior
    that a real cluster would perform between the map and reduce phases."""
    here = Path(__file__).parent
    start = time.perf_counter()

    with input_path.open("rb") as infile:
        mapper = subprocess.Popen(["python", str(here / "mapper.py")], stdin=infile, stdout=subprocess.PIPE)
        sorter = subprocess.Popen(["sort"], stdin=mapper.stdout, stdout=subprocess.PIPE)
        reducer = subprocess.Popen(["python", str(here / "reducer.py")], stdin=sorter.stdout, stdout=subprocess.PIPE)
        mapper.stdout.close()
        sorter.stdout.close()
        output, _ = reducer.communicate()

    elapsed = time.perf_counter() - start
    print(f"[MapReduce-style] {len(output.decode().splitlines())} distinct skills, {elapsed:.2f}s")
    return elapsed


def run_spark_style(input_path: Path) -> float:
    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F

    spark = SparkSession.builder.appName("careerlens-benchmark").master("local[*]").getOrCreate()

    start = time.perf_counter()
    df = spark.read.json(str(input_path))
    counts = (
        df.select(F.explode("required_skills").alias("skill"))
        .groupBy("skill")
        .count()
        .collect()  # small result (one row per distinct skill) — safe to bring to the driver
    )
    elapsed = time.perf_counter() - start

    print(f"[Spark]          {len(counts)} distinct skills, {elapsed:.2f}s")
    spark.stop()
    return elapsed


def main(input_path: Path) -> None:
    print(f"Benchmarking against: {input_path}\n")

    mr_time = run_mapreduce_style(input_path)
    spark_time = run_spark_style(input_path)

    if mr_time > 0:
        reduction = (mr_time - spark_time) / mr_time * 100
        print(f"\nSpark was {reduction:.1f}% faster than the MapReduce-style pipeline "
              f"on this run ({mr_time:.2f}s -> {spark_time:.2f}s).")
        print("Re-run a few times and average — single-run timings are noisy, especially "
              "on a laptop with other processes competing for CPU.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    args = parser.parse_args()
    main(Path(args.input))

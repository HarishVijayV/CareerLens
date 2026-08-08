"""
Runs the SAME aggregation (skill-frequency count across all postings) two ways on the
same input, times both, and reports the difference — so the "% faster with Spark" number
on your resume is one you measured yourself, not one you inherited.

Why Spark wins (the actual explanation, worth being able to give out loud):
  * MapReduce writes intermediate results to DISK between the map and reduce stages. The
    `sort` step in the pipe below is doing exactly that — the same disk-backed shuffle a
    real Hadoop cluster performs between phases.
  * Spark keeps intermediate results in MEMORY across a DAG of transformations, and only
    spills to disk when it has to. No serialize-to-disk-and-read-back per stage.
  * Spark also parallelizes across all cores here (local[*]); the Unix-pipe version is
    essentially a single pass through three processes.

Run each engine N times and report the MEDIAN — single-run timings on a laptop are noisy
(background processes, page cache state, JIT warmup), and quoting a number from one run
is exactly the kind of claim an interviewer will poke at.

Usage:
    python mapreduce_demo/benchmark_compare.py --input data/raw/postings.jsonl --runs 3
"""
import argparse
import json
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "spark_jobs"))


def run_mapreduce_style(input_path: Path) -> tuple[float, int]:
    """mapper.py | sort | reducer.py — the classic three-stage MapReduce shape, with
    `sort` standing in for Hadoop's shuffle."""
    here = Path(__file__).parent
    start = time.perf_counter()

    with input_path.open("rb") as infile:
        mapper = subprocess.Popen(
            [sys.executable, str(here / "mapper.py")], stdin=infile, stdout=subprocess.PIPE
        )
        sorter = subprocess.Popen(["sort"], stdin=mapper.stdout, stdout=subprocess.PIPE)
        reducer = subprocess.Popen(
            [sys.executable, str(here / "reducer.py")], stdin=sorter.stdout, stdout=subprocess.PIPE
        )
        mapper.stdout.close()
        sorter.stdout.close()
        output, _ = reducer.communicate()

    elapsed = time.perf_counter() - start
    return elapsed, len(output.decode().splitlines())


def run_spark_style(input_path: Path) -> tuple[float, int]:
    from pyspark.sql import functions as F

    from spark_common import build_spark

    spark = build_spark("careerlens-benchmark")
    # Warm the JVM/session first so we time the JOB, not Spark's one-off startup cost.
    # Including startup would inflate Spark's number and make the comparison dishonest.
    spark.read.json(str(input_path)).limit(1).count()

    start = time.perf_counter()
    counts = (
        spark.read.json(str(input_path))
        .select(F.explode("required_skills").alias("skill"))
        .groupBy("skill")
        .count()
        .collect()  # small result — one row per distinct skill — safe to pull to driver
    )
    elapsed = time.perf_counter() - start

    spark.stop()
    return elapsed, len(counts)


def main(input_path: Path, runs: int, out_path: Path | None) -> None:
    row_count = sum(1 for _ in input_path.open("rb"))
    print(f"Input: {input_path}  ({row_count:,} rows, {input_path.stat().st_size / 1e6:.0f} MB)")
    print(f"Machine: {platform.processor() or platform.machine()}, {platform.system()}")
    print(f"Runs per engine: {runs}\n")

    mr_times, spark_times = [], []
    skills_mr = skills_spark = 0

    for i in range(1, runs + 1):
        elapsed, skills_mr = run_mapreduce_style(input_path)
        mr_times.append(elapsed)
        print(f"  [MapReduce] run {i}: {elapsed:6.2f}s  ({skills_mr} distinct skills)")

    print()
    for i in range(1, runs + 1):
        elapsed, skills_spark = run_spark_style(input_path)
        spark_times.append(elapsed)
        print(f"  [Spark]     run {i}: {elapsed:6.2f}s  ({skills_spark} distinct skills)")

    mr_median = statistics.median(mr_times)
    spark_median = statistics.median(spark_times)
    reduction = (mr_median - spark_median) / mr_median * 100
    speedup = mr_median / spark_median

    # Correctness check: a faster wrong answer is worthless. Both engines must agree.
    assert skills_mr == skills_spark, (
        f"Engines disagree ({skills_mr} vs {skills_spark} skills) — the benchmark is "
        "meaningless unless both compute the same result."
    )

    print("\n" + "=" * 62)
    print(f"  MapReduce-style median : {mr_median:6.2f}s")
    print(f"  Spark median           : {spark_median:6.2f}s")
    print(f"  Spark is {reduction:.1f}% faster ({speedup:.2f}x speedup)")
    print(f"  Both engines agree: {skills_mr} distinct skills")
    print("=" * 62)

    if out_path:
        results = {
            "input_rows": row_count,
            "input_mb": round(input_path.stat().st_size / 1e6, 1),
            "runs_per_engine": runs,
            "mapreduce_times_sec": [round(t, 3) for t in mr_times],
            "spark_times_sec": [round(t, 3) for t in spark_times],
            "mapreduce_median_sec": round(mr_median, 3),
            "spark_median_sec": round(spark_median, 3),
            "reduction_percent": round(reduction, 1),
            "speedup_x": round(speedup, 2),
            "distinct_skills": skills_mr,
            "platform": f"{platform.system()} {platform.machine()}",
        }
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(results, indent=2))
        print(f"\nResults saved -> {out_path}  (cite these numbers, not a guess)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--out", default="data/benchmark_results.json")
    args = parser.parse_args()
    main(Path(args.input), args.runs, Path(args.out) if args.out else None)

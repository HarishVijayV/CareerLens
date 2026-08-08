"""
Salary model — and, importantly, what it's FOR.

A model that nothing consumes is decoration. This one exists to answer a question a job
seeker actually has: **"is this posting paying fairly for what it is?"** The model
predicts what a role with this seniority/region/remote/skill profile typically pays, and
the difference between that prediction and the advertised salary becomes a
`salary_vs_market` figure attached to every posting — surfaced in the jobs API and
searchable ("show me roles paying above market").

That also dictates the serving pattern: predictions are computed in **batch** here and
written to the warehouse, not computed per request. Batch scoring is the right default —
the features only change when the pipeline runs, so paying Spark's startup cost per HTTP
request would be absurd. Real-time inference is for when features depend on the request
itself.

Model choice: gradient-boosted trees, because the features are a categorical/numeric mix
and GBT handles that without much preprocessing, and its feature importances give a
concrete thing to point at. A LinearRegression baseline is trained alongside — comparing
against a simple baseline is what turns "I trained a model" into "I evaluated a model".
If the complicated model can't beat the simple one, that's a finding, not a failure.

Trained on REAL postings only (--real-only, the pipeline default), and the reason is the
most useful thing in this file.

Trained on everything, it scored R²=0.898 — which looked excellent and meant nothing.
96% of the importance was seniority, because that is precisely how the synthetic
generator computes salary. The model had recovered the generator, not the market.

Trained on the ~3k live postings instead:

    R²          0.898  ->  0.617      (lower, and more honest)
    GBT vs linear  +0.033  ->  +0.142  (the complex model now EARNS its place)
    top feature  seniority 96%  ->  region 72%, seniority 25%, skills 3%

Region dominating is a true fact about the world — a US role pays multiples of an Indian
one — rather than an artefact. Preferring the lower number is the point: a high score that
only proves your generator was deterministic is worth nothing in an interview, and the
first follow-up question destroys it.

Every posting is still SCORED, including synthetic ones; --real-only narrows what the
model learns from, never what it is applied to.

Usage:
    python spark_jobs/mllib_salary_model.py --input data/curated/postings.parquet
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from pyspark.ml import Pipeline  # noqa: E402
from pyspark.ml.evaluation import RegressionEvaluator  # noqa: E402
from pyspark.ml.feature import StringIndexer, VectorAssembler  # noqa: E402
from pyspark.ml.regression import GBTRegressor, LinearRegression  # noqa: E402
from pyspark.sql import functions as F  # noqa: E402

from spark_common import build_spark  # noqa: E402

FEATURES = ["seniority_idx", "region_idx", "remote_int", "skill_count"]


def run(input_path: str, model_out: str | None, metrics_out: str | None,
        scores_out: str | None, real_only: bool = False) -> None:
    spark = build_spark("careerlens-mllib")

    df = (
        spark.read.parquet(input_path)
        .filter(F.col("salary_clean").isNotNull())
        # skill_count is computed by the ETL job; this model just consumes it.
        # VectorAssembler needs numerics — booleans aren't accepted directly.
        .withColumn("remote_int", F.col("remote").cast("int"))
    )

    # Scoring must still cover EVERY posting — a synthetic row with no pay band would
    # render as a blank column in the UI. So the real-only choice narrows what the model
    # LEARNS from, never what it is applied to.
    score_df = df

    if real_only:
        # Train on live postings only. The trade is explicit: far fewer rows, but they
        # carry real market structure (a US role genuinely pays multiples of an Indian one)
        # instead of a generator's formula. Expect a LOWER R^2 — real salaries are noisy in
        # ways generated ones are not, and a lower number earned on real data is worth more
        # than a high one that merely proves the generator was deterministic.
        df = df.filter(F.col("is_real") == True)  # noqa: E712 — Spark Column, not a bool

    total = df.count()
    label = "real postings only" if real_only else "all postings"
    print(f"Training rows (non-null salary, {label}): {total:,}")

    if total < 500:
        raise SystemExit(
            f"Only {total:,} rows to train on — too few to split and evaluate meaningfully. "
            "Run the ingest first, or drop --real-only."
        )

    # Split BEFORE fitting anything, so no information from the test set can leak into
    # training via the indexers. Fitting the full Pipeline on train only is what keeps
    # that guarantee.
    train_df, test_df = df.randomSplit([0.8, 0.2], seed=42)
    print(f"Train: {train_df.count():,}   Test: {test_df.count():,}")

    stages = [
        StringIndexer(inputCol="seniority", outputCol="seniority_idx", handleInvalid="keep"),
        StringIndexer(inputCol="region", outputCol="region_idx", handleInvalid="keep"),
        VectorAssembler(inputCols=FEATURES, outputCol="features", handleInvalid="skip"),
    ]

    results = {}

    for name, estimator in [
        ("LinearRegression (baseline)", LinearRegression(featuresCol="features", labelCol="salary_clean")),
        ("GBTRegressor", GBTRegressor(featuresCol="features", labelCol="salary_clean", maxIter=50, seed=42)),
    ]:
        model = Pipeline(stages=stages + [estimator]).fit(train_df)
        predictions = model.transform(test_df)

        evaluator = RegressionEvaluator(labelCol="salary_clean", predictionCol="prediction")
        rmse = evaluator.setMetricName("rmse").evaluate(predictions)
        mae = evaluator.setMetricName("mae").evaluate(predictions)
        r2 = evaluator.setMetricName("r2").evaluate(predictions)

        print(f"\n--- {name} ---")
        print(f"  RMSE : ${rmse:,.0f}   (typical error, punishes big misses)")
        print(f"  MAE  : ${mae:,.0f}   (typical error, treats all misses equally)")
        print(f"  R^2  : {r2:.3f}      (share of salary variance explained)")

        results[name] = {"rmse": round(rmse), "mae": round(mae), "r2": round(r2, 4)}

        if name == "GBTRegressor":
            importances = model.stages[-1].featureImportances.toArray()
            print("\n  Feature importances:")
            for feature, importance in sorted(
                zip(FEATURES, importances), key=lambda pair: pair[1], reverse=True
            ):
                print(f"    {feature:<15} {importance:.3f}  {'#' * int(importance * 40)}")
            results[name]["feature_importances"] = {
                f: round(float(i), 4) for f, i in zip(FEATURES, importances)
            }

            predictions.select(
                "title", "seniority", "region", "salary_clean", F.round("prediction").alias("predicted")
            ).show(10, truncate=False)

            if model_out:
                model.write().overwrite().save(model_out)
                print(f"Model saved -> {model_out}")

            if scores_out:
                # BATCH SCORING — score every posting (not just the test split) and write
                # the result for the warehouse to load. This is what makes the model part
                # of the product instead of a training script that prints metrics and
                # exits.
                scored = (
                    model.transform(score_df)
                    .withColumn("predicted_salary", F.round("prediction").cast("long"))
                    .withColumn(
                        "salary_vs_market",
                        F.round(F.col("salary_clean") - F.col("prediction")).cast("long"),
                    )
                    .withColumn(
                        "pay_band",
                        F.when(F.col("salary_vs_market") > 10000, "above_market")
                        .when(F.col("salary_vs_market") < -10000, "below_market")
                        .otherwise("at_market"),
                    )
                    .select("posting_id", "predicted_salary", "salary_vs_market", "pay_band")
                )

                print("\nPay-band distribution (what the model is FOR):")
                scored.groupBy("pay_band").count().orderBy(F.desc("count")).show(truncate=False)

                scored.write.mode("overwrite").parquet(scores_out)
                print(f"Scored postings written -> {scores_out}")

    if metrics_out:
        Path(metrics_out).parent.mkdir(parents=True, exist_ok=True)
        Path(metrics_out).write_text(json.dumps(results, indent=2))
        print(f"Metrics saved -> {metrics_out}")

    spark.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--model-out", default="data/models/salary_gbt")
    parser.add_argument("--metrics-out", default="data/model_metrics.json")
    parser.add_argument("--scores-out", default="data/curated/postings_scored.parquet")
    parser.add_argument(
        "--real-only",
        action="store_true",
        help="train on live job-board postings only (still scores every posting)",
    )
    args = parser.parse_args()
    run(args.input, args.model_out, args.metrics_out, args.scores_out, args.real_only)

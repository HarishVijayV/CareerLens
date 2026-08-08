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

Honest caveat, worth stating before anyone asks: on the SYNTHETIC data, salary is
generated almost entirely from seniority, so the model recovers that and reports
seniority at ~1.0 importance with R²≈0.91. That's a correct result about a synthetic
world, not evidence the model would work on real postings. On real data expect a much
lower R² and a broader importance spread.

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
        scores_out: str | None) -> None:
    spark = build_spark("careerlens-mllib")

    df = (
        spark.read.parquet(input_path)
        .filter(F.col("salary_clean").isNotNull())
        # skill_count is computed by the ETL job; this model just consumes it.
        # VectorAssembler needs numerics — booleans aren't accepted directly.
        .withColumn("remote_int", F.col("remote").cast("int"))
    )

    total = df.count()
    print(f"Training rows (non-null salary): {total:,}")

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
                    model.transform(df)
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
    args = parser.parse_args()
    run(args.input, args.model_out, args.metrics_out, args.scores_out)

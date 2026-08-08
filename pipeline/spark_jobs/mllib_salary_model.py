"""
Trains a real Spark MLlib model on the curated data from etl_clean_jobs.py — the direct
evolution of "Spark MLlib" on the original resume line, except this one you trained and
can walk through line by line.

Model: gradient-boosted trees regressor predicting salary from seniority, region, remote
flag and skill count. GBT because it handles the categorical + numeric feature mix here
without much preprocessing, and its feature-importance output gives you a concrete thing
to point at ("here's what actually drives salary in this dataset").

Also trains a LinearRegression baseline. Always having a simple baseline to compare
against is what turns "I trained a model" into "I evaluated a model" — if the fancy model
can't beat the simple one, that's a finding, not a failure.

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


def run(input_path: str, model_out: str | None, metrics_out: str | None) -> None:
    spark = build_spark("careerlens-mllib")

    df = (
        spark.read.parquet(input_path)
        .filter(F.col("salary_clean").isNotNull())
        .withColumn("skill_count", F.size(F.coalesce(F.col("required_skills"), F.array())))
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
    args = parser.parse_args()
    run(args.input, args.model_out, args.metrics_out)

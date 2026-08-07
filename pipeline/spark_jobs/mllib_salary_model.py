"""
Trains a real Spark MLlib model on the curated data from etl_clean_jobs.py — this is the
direct evolution of "Spark MLlib" on the original resume line, except this one you can
walk through line by line.

Model: gradient-boosted trees regressor predicting salary from seniority, region,
remote flag, and skill count. Not because GBT is exotic — because it handles the
categorical + numeric feature mix here without much preprocessing, and its feature-
importance output gives you an easy, concrete thing to point at in an interview
("here's what actually drives salary in this dataset").

Usage:
    python mllib_salary_model.py --input data/curated/postings.parquet
"""
import argparse

from pyspark.ml import Pipeline
from pyspark.ml.evaluation import RegressionEvaluator
from pyspark.ml.feature import StringIndexer, VectorAssembler
from pyspark.ml.regression import GBTRegressor
from pyspark.sql import SparkSession, functions as F


def build_spark() -> SparkSession:
    return SparkSession.builder.appName("careerlens-mllib").master("local[*]").getOrCreate()


def run(input_path: str) -> None:
    spark = build_spark()

    df = (
        spark.read.parquet(input_path)
        .filter(F.col("salary_clean").isNotNull())
        .withColumn("skill_count", F.size(F.coalesce(F.col("required_skills"), F.array())))
    )

    print(f"Training rows (non-null salary): {df.count():,}")

    # Categorical -> numeric indices; MLlib's estimators need numeric feature vectors,
    # they don't consume raw strings the way, say, a pandas + sklearn pipeline sometimes
    # implicitly can.
    seniority_idx = StringIndexer(inputCol="seniority", outputCol="seniority_idx", handleInvalid="keep")
    region_idx = StringIndexer(inputCol="region", outputCol="region_idx", handleInvalid="keep")

    assembler = VectorAssembler(
        inputCols=["seniority_idx", "region_idx", "remote", "skill_count"],
        outputCol="features",
        handleInvalid="skip",
    )

    gbt = GBTRegressor(featuresCol="features", labelCol="salary_clean", maxIter=50)

    pipeline = Pipeline(stages=[seniority_idx, region_idx, assembler, gbt])

    train_df, test_df = df.randomSplit([0.8, 0.2], seed=42)
    model = pipeline.fit(train_df)
    predictions = model.transform(test_df)

    evaluator = RegressionEvaluator(labelCol="salary_clean", predictionCol="prediction", metricName="rmse")
    rmse = evaluator.evaluate(predictions)
    r2 = evaluator.setMetricName("r2").evaluate(predictions)

    print(f"Test RMSE: ${rmse:,.0f}")
    print(f"Test R^2:  {r2:.3f}")

    gbt_model = model.stages[-1]
    print("\nFeature importances (seniority_idx, region_idx, remote, skill_count):")
    print(gbt_model.featureImportances)

    predictions.select("title", "seniority", "region", "salary_clean", "prediction").show(10)

    spark.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    args = parser.parse_args()
    run(args.input)

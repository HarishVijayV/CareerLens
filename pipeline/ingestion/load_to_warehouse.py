"""
The bridge between Spark's output and dbt's input: Spark writes curated Parquet, this
script loads it into a `raw.postings` table, and dbt takes over from there (see
pipeline/dbt/models/staging/sources.yml). Deliberately plain pandas + SQLAlchemy instead
of Spark's JDBC writer — the destination table is small enough (aggregated/curated, not
raw-scale) that this is simpler and easier to explain than configuring Spark JDBC.

Usage:
    python load_to_warehouse.py --input data/curated/postings.parquet \
        --database-url postgresql+psycopg://careerlens:change_me@localhost:5432/careerlens
"""
import argparse

import pandas as pd
from sqlalchemy import create_engine, text


def run(input_path: str, database_url: str) -> None:
    df = pd.read_parquet(input_path)
    print(f"Loaded {len(df):,} rows from {input_path}")

    engine = create_engine(database_url)
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS raw"))

    df.to_sql("postings", engine, schema="raw", if_exists="replace", index=False, chunksize=10_000)
    print(f"Loaded into raw.postings ({database_url.split('@')[-1]})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--database-url", required=True)
    args = parser.parse_args()
    run(args.input, args.database_url)

"""
The bridge between Spark's output and dbt's input: Spark writes curated Parquet, this
loads it into `raw.*` tables, and dbt takes over from there (pipeline/dbt/models/).

Two things worth understanding here:

1. Spark writes a DIRECTORY of part-*.parquet files, not a single file (one part per
   output partition — that's what lets the write itself be parallel). We glob the parts
   explicitly rather than handing the directory to pandas, because a stray `_SUCCESS`
   marker file in there makes some pandas/pyarrow versions silently return ZERO rows
   instead of erroring — a genuinely nasty bug to chase, and one this script hit for
   real.

2. Loading via COPY, not INSERT. Postgres COPY streams rows in a single bulk operation
   instead of round-tripping per row; on ~200k rows the difference is minutes vs
   seconds. Worth knowing by name — "how would you bulk-load a warehouse" is a standard
   data-engineering interview question.

Usage:
    python ingestion/load_to_warehouse.py \
        --curated-dir data/curated \
        --database-url postgresql://careerlens:change_me@localhost:5432/careerlens
"""
import argparse
import csv
import io
import sys
from pathlib import Path

import pandas as pd
import psycopg

sys.path.insert(0, str(Path(__file__).parent.parent))

from paths import long_path  # noqa: E402

# curated parquet dir (relative to --curated-dir) -> destination table in schema `raw`
TABLE_MAP = {
    "postings.parquet": "postings",
    "postings_posting_skills.parquet": "posting_skills",
    "postings_skill_demand.parquet": "skill_demand",
    "postings_salary_by_seniority.parquet": "salary_by_seniority",
    "postings_postings_by_month.parquet": "postings_by_month",
    "postings_salary_by_region.parquet": "salary_by_region",
}

# Postgres type overrides; anything not listed is inferred from the pandas dtype.
TYPE_OVERRIDES = {"remote": "boolean", "salary_clean": "bigint", "posted_month": "integer"}


def read_spark_parquet(parquet_dir: Path) -> pd.DataFrame:
    parts = sorted(parquet_dir.glob("part-*.parquet"))
    if not parts:
        raise FileNotFoundError(f"No part-*.parquet files in {parquet_dir}")
    # long_path() matters here — see pipeline/paths.py. Without it these reads fail with
    # FileNotFoundError on Windows for files that demonstrably exist.
    return pd.concat((pd.read_parquet(long_path(p)) for p in parts), ignore_index=True)


def _pg_type(series: pd.Series, column: str) -> str:
    if column in TYPE_OVERRIDES:
        return TYPE_OVERRIDES[column]
    dtype = str(series.dtype)
    if dtype.startswith("int"):
        return "bigint"
    if dtype.startswith("float"):
        return "double precision"
    if dtype.startswith("bool"):
        return "boolean"
    return "text"


def load_table(conn: psycopg.Connection, df: pd.DataFrame, table: str) -> None:
    df = df.copy()
    columns = list(df.columns)
    pg_types = {c: _pg_type(df[c], c) for c in columns}

    # A column of whole numbers that also contains NULLs comes back from pandas as
    # float64, because classic numpy ints can't represent NaN. It then serializes as
    # "184909.0", which Postgres rejects for a bigint column. pandas' nullable "Int64"
    # dtype holds integers AND missing values, so the CSV gets "184909" and an empty
    # field for nulls — exactly what COPY expects.
    for column, pg_type in pg_types.items():
        if pg_type in ("bigint", "integer") and str(df[column].dtype).startswith("float"):
            df[column] = df[column].round().astype("Int64")

    column_defs = ", ".join(f'"{c}" {pg_types[c]}' for c in columns)

    with conn.cursor() as cur:
        # CASCADE is required, not lazy: dbt's staging models are VIEWS over raw.*, so a
        # plain DROP fails on the SECOND run with "other objects depend on it" — a bug
        # that only appears once you re-run the pipeline, which is exactly why re-running
        # it is part of testing. Dropping the dependent views is safe because dbt rebuilds
        # every model on each `dbt run`, and raw.* is owned solely by this loader.
        cur.execute(f'DROP TABLE IF EXISTS raw."{table}" CASCADE')
        cur.execute(f'CREATE TABLE raw."{table}" ({column_defs})')

        buffer = io.StringIO()
        df.to_csv(buffer, index=False, header=False, quoting=csv.QUOTE_MINIMAL, na_rep="")
        buffer.seek(0)

        column_list = ", ".join(f'"{c}"' for c in columns)
        copy_sql = f'COPY raw."{table}" ({column_list}) FROM STDIN WITH (FORMAT csv, NULL \'\')'
        with cur.copy(copy_sql) as copy:
            copy.write(buffer.read())

    print(f"  raw.{table:<22} {len(df):>9,} rows")


def run(curated_dir: Path, database_url: str) -> None:
    # psycopg wants a plain libpq URL; strip SQLAlchemy's "+psycopg" driver suffix so
    # the same connection string works whether it came from .env or the CLI.
    database_url = database_url.replace("postgresql+psycopg://", "postgresql://")

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE SCHEMA IF NOT EXISTS raw")

        for parquet_name, table in TABLE_MAP.items():
            parquet_dir = curated_dir / parquet_name
            if not parquet_dir.exists():
                print(f"  (skipping {parquet_name} — not found)")
                continue
            load_table(conn, read_spark_parquet(parquet_dir), table)

        conn.commit()

    print("\nLoaded into schema `raw`. Next: cd pipeline/dbt && dbt run && dbt test")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--curated-dir", default="data/curated")
    parser.add_argument("--database-url", required=True)
    args = parser.parse_args()
    run(Path(args.curated_dir), args.database_url)

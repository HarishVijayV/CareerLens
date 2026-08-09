# Data Engineering Layer — What's Here and Why

This is the part of the project that directly upgrades your existing resume line
("distributed pipeline for 15M+ records using Hadoop, MapReduce, Spark MLlib... 40%
computation time reduction"). Everything below is designed so you can explain not just
*that* you used a tool, but *why* it's there and what would break without it.

## 1. Ingestion — `pipeline/ingestion/`

Two sources, on purpose:

- **`job_apis.py`** — pulls real postings from free, legit public APIs (Adzuna, RemoteOK,
  Arbeitnow). Real data means real messiness (missing fields, inconsistent formats) — good for
  a genuine cleaning story.
- **`generate_synthetic_data.py`** — a Faker-based generator that scales the dataset up to
  millions of rows (mirrors your original "15M+ records" claim) by synthesizing realistic
  postings with seasonality, regional trends, and deliberately injected anomalies/duplicates —
  so your anomaly-detection and dedup logic has something real to catch.

Both write raw JSON/CSV files that get dropped into the raw landing zone (HDFS locally).

## 2. Storage — HDFS (local) → S3-equivalent (cloud)

A **single-node, pseudo-distributed Hadoop cluster** (via Docker) acts as the raw "data lake."
You do not need a multi-node cluster to explain HDFS correctly — a single-node setup still
demonstrates the same concepts (blocks, replication factor, NameNode/DataNode split) and is
what most real portfolio projects use. Raw, unprocessed files land here first, exactly as they
were scraped/generated — nothing is cleaned before this point.

Why not skip straight to Postgres? Because in a real pipeline you never want to throw away the
raw input — if a downstream bug corrupts your cleaned data, you can always reprocess from the
untouched raw layer. That's the actual reason data lakes exist.

## 3. Processing — PySpark — `pipeline/spark_jobs/`

- **`etl_clean_jobs.py`** — reads raw files from HDFS, deduplicates, normalizes fields
  (salary ranges, location strings), and extracts structured skill tags from free-text
  descriptions using simple NLP (regex + a skill taxonomy list; swappable for a proper NLP
  model later). Writes curated Parquet files back to HDFS/warehouse.
- **`mllib_salary_model.py`** — trains an actual Spark MLlib model (linear regression /
  gradient-boosted trees) to predict expected salary from job features (title, seniority,
  location, skill count). This is the direct callback to "Spark MLlib" on your resume — except
  now it's a model you trained yourself on data you can describe.

Why Spark and not plain pandas? Spark's execution model (lazy evaluation, DAG scheduling,
in-memory shuffles) is what actually lets it scale past what a single machine's RAM can hold —
and that's precisely the point the MapReduce benchmark below proves.

## Measured results (from actually running this)

| Metric | Value |
|---|---|
| Raw rows in | 154,911 (4,911 live Adzuna postings + 150,000 generated) |
| After dedup | 151,883 (3,028 duplicates removed) |
| Spark vs MapReduce | **57.1% faster / 2.33× speedup** (median of 3 runs each) |
| MLlib GBT (real postings only) | R² = 0.617, RMSE $36,671 |
| LinearRegression baseline | R² = 0.475, RMSE $42,916 |
| Warehouse rows | 151,883 postings + 737,525 skill rows |
| dbt | 5 models, 17/17 tests passing |

Committed as JSON in `pipeline/data/`. Reproduce with `python run_pipeline.py --benchmark`.

**Why the model trains on real postings only — and why the lower score is the better
result.** Trained on all 151,883 rows it scored R²=0.898, which looked excellent and meant
nothing: 96% of the feature importance was `seniority`, because that is precisely how the
synthetic generator computes salary. The model had recovered the generator, not the job
market.

Retrained on the 2,992 live postings that carry a salary, R² falls to 0.617 — and three
things improve. `region` becomes the dominant feature at 72%, which is a true fact about
the world (a US role pays multiples of an Indian one) rather than an artefact. GBT now
beats the linear baseline by 4× the margin (+0.142 vs +0.033), so the complex model earns
its place instead of tying. And the residual error is real market noise rather than an
unlearned formula.

*Prefer the number you can defend.* A high score that only proves your generator was
deterministic dies on the first follow-up question. Every posting is still scored —
`--real-only` narrows what the model LEARNS from, never what it is applied to.

### Ingestion is driven by the user's profile

`job_apis.py --from-profiles` reads every user's target roles and countries straight from
the database and unions them into the Adzuna query. Before that flag the term list was
hardcoded, so the profile page claimed to "drive which jobs get fetched" while doing
nothing of the kind — a user targeting MLOps in Bangalore got a warehouse of roles they
would never apply to.

Read from the database rather than the API because the pipeline is a trusted backend
process that already holds the credentials, and an authenticated per-user endpoint would
mean minting a token for a batch job with no user. Defaults are always unioned in, so an
empty profile still fetches something and market-wide analytics keep a broad sample.

### Indexes are built by dbt, not by hand

The analytics schema had **zero** indexes: dbt creates tables and never indexes them, so
every search sequentially scanned 151,883 rows and the profile-ranking subquery scanned
737,525 bridge rows per row it touched. Search took ~2.0s and exhausted Postgres' shared
memory under load.

They are attached as dbt **post-hooks** (`macros/index_marts.sql`) rather than created
manually, because a `table` materialisation is dropped and recreated on every run — an
index made by hand survives until the next `dbt run` and then silently disappears. Each
index is justified by a specific query rather than added speculatively, since every index
costs write time on each load, and the macro no-ops on Snowflake, which has no
`CREATE INDEX`.

Result: **2.0s → 0.52s**, a 3.8× improvement, with all 17 tests still passing.

## 4. The MapReduce vs Spark benchmark — `pipeline/mapreduce_demo/`

- **`mapreduce_wordcount.py`** — the *same* aggregation (skill-frequency count across all
  postings) implemented the classic MapReduce way (map → shuffle → reduce, no in-memory
  reuse between stages).
- **`benchmark_compare.py`** — runs both the MapReduce version and the equivalent Spark job on
  the same dataset size, times them, and prints a comparison.

This recreates your resume's "40% computation time reduction" claim with numbers you generated
yourself. The real reason Spark wins: MapReduce writes intermediate results to disk between
every stage; Spark keeps them in memory across a DAG of transformations. Being able to say
*that*, not just "Spark is faster," is what separates "used a tool" from "understands the
tool."

## 5. Event streaming — Kafka

Not every part of this pipeline should wait for a scheduled batch run. When a new posting is
scraped, or a new email is classified, that's an *event* — published to a Kafka topic
(`new-posting-scraped`, `email-classified`) and consumed immediately by whichever service
cares (the worker service, the agent service). This is what makes parts of the system
event-driven instead of purely cron-based, which is exactly the distinction interviewers probe
for ("batch vs streaming — when would you use which?").

## 6. Orchestration — Airflow — `pipeline/airflow/dags/`

One DAG (`job_pipeline_dag.py`) wires the whole batch side together on a schedule: ingest →
land in HDFS → Spark ETL → MapReduce benchmark (optional/manual trigger) → MLlib training →
load curated tables into Postgres and Snowflake → dbt run → dbt test. Airflow is what lets you
say "here's the DAG" in an interview instead of "I ran some scripts."

## 7. Warehouse + transformation — Snowflake + dbt — `pipeline/dbt/`

Curated data lands in two places on purpose:

- **Postgres** — fast, low-latency reads for the live app and the AI agents (they need answers
  in seconds, not warehouse-query time).
- **Snowflake** — the analytics warehouse for heavier historical/BI-style queries. Snowflake is
  SaaS, so you can start using its free trial today, even before touching cloud deployment for
  the rest of the app.

dbt sits on top of both and does two jobs: (1) SQL-based transformations into a proper **star
schema** (fact table: postings/applications; dimensions: company, skill, location, time), and
(2) automated **data-quality tests** (not-null checks, uniqueness, accepted-value ranges) that
fail loudly if upstream data goes bad — a core "did you think about reliability" signal.

## 8. Data modeling — the star schema

```
                 dim_company
                      │
dim_location ── fact_job_posting ── dim_skill (many-to-many via bridge table)
                      │
                 dim_time
```

Plus a second fact table, `fact_application`, tracking your own applications (status over
time, resume version used) — this is what powers the funnel analytics in the copilot.

## Summary — one line per tool, for quick recall before an interview

| Tool | One-line role |
|---|---|
| HDFS | Raw, immutable landing zone for scraped/generated data |
| PySpark | Cleans, dedupes, extracts fields, aggregates at scale |
| MapReduce (one job) | Benchmark partner to prove *why* Spark is faster, with real numbers |
| Spark MLlib | Trains a real model (salary prediction) on the cleaned data |
| Kafka | Event bus for the real-time bits (new posting, new email) |
| Airflow | Schedules and orchestrates every pipeline step as a DAG |
| dbt | SQL transformations into a star schema + automated data-quality tests |
| Snowflake | Cloud analytics warehouse for historical/BI queries |
| Postgres | Fast serving layer for the live app and AI agents |

## Troubleshooting (all of these were hit for real — see LESSONS.md)

| Symptom | Cause | Fix |
|---|---|---|
| `SocketTimeoutException: Accept timed out` | Spark's Python workers can't start — `python` resolves to the Windows Store stub | handled in `spark_common.py` (pins `PYSPARK_PYTHON`) |
| Reads work, every WRITE fails with `HADOOP_HOME unset` | Windows needs `winutils.exe` + `hadoop.dll` | installed at `~/hadoop`, auto-detected |
| `FileNotFoundError` on a file that exists | Windows 260-char path limit | `pipeline/paths.py` adds the `\\?\` prefix |
| Loader reports success but 0 rows | `pandas.read_parquet` on a Spark output *directory* returns empty | glob `part-*.parquet` explicitly |
| `invalid input syntax for type bigint: "1.0"` | NULLs promote int columns to float in pandas | cast to nullable `Int64` |
| `cannot drop table ... other objects depend on it` | dbt views depend on `raw.*`; only appears on the SECOND run | `DROP TABLE ... CASCADE` |

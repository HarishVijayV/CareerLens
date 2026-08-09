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
| Raw rows in | 205,397 (5,397 live Adzuna postings + 200,000 generated) |
| After dedup | 201,356 (4,041 duplicates removed) |
| Spark vs MapReduce | **57.1% faster / 2.33× speedup** (median of 3 runs each) |
| MLlib GBT (real postings only) | R² = 0.617, RMSE $36,671 |
| LinearRegression baseline | R² = 0.475, RMSE $42,916 |
| Warehouse rows | 201,356 postings + 982,853 skill rows |
| dbt | 5 models, 17/17 tests passing |

Committed as JSON in `pipeline/data/`. Reproduce with `python run_pipeline.py --benchmark`.

**Why the model trains on real postings only — and why the lower score is the better
result.** Trained on all 201,356 rows it scored R²=0.898, which looked excellent and meant
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
every search sequentially scanned 201,356 rows and the profile-ranking subquery scanned
982,853 bridge rows per row it touched. Search took ~2.0s and exhausted Postgres' shared
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

---

## Is this over-engineered? An honest audit, tool by tool

At 201,356 rows a laptop and a few Python scripts would do the job. Several tools here are
therefore **demonstrations of a pattern, not solutions to a problem I actually had** — and
saying so first is worth more than hoping nobody asks. An interviewer who works with these
tools daily will spot an unjustified Kafka in about ten seconds.

The useful framing is not "is it needed?" but **"at what point does it become needed, and
what would I use before that?"**

| Tool | Needed at 152k rows? | What would do instead | When it genuinely becomes necessary |
|---|---|---|---|
| **PySpark** | No — pandas fits in RAM | pandas | When data exceeds one machine's memory, or a job must survive a node dying mid-run |
| **Airflow** | No | `cron` + a shell script | When you have dependencies between tasks, retries, backfills, and need to answer "why did last Tuesday fail?" |
| **Kafka** | No | a direct function call | When several independent consumers react to one event and must not break each other |
| **dbt** | **Yes** | hand-written SQL, worse | Immediately — the tests are the point, and they scale down fine |
| **Star schema** | **Yes** | one wide table | Immediately — it is a modelling choice, not a scale choice |
| **Parquet** | **Yes** | CSV, slower and larger | Immediately — free win at any size |
| **Redis** | **Yes** | none | Immediately — analytics queries are slow and repeat constantly |
| **Snowflake** | No | Postgres | When analytical scans outgrow one server, or storage and compute need to scale apart |
| **MapReduce** | No, deliberately | nothing | Never. It is here to *measure* what Spark improved, then be retired |
| **Kubernetes** | No | Docker Compose | When you need rolling deploys, self-healing, or horizontal scaling |

#### The three that are honestly demonstrations

**Airflow vs a cron job.** For seven sequential steps run once a day, `cron` genuinely
does the job in one line. What cron does not give you:

* **Task-level retries.** Cron reruns the whole 7-minute pipeline; Airflow retries the one
  step that hit a network blip and keeps everything already computed.
* **Dependencies.** Cron runs on a clock. Airflow runs `dbt test` because `dbt run`
  succeeded, and skips the rest when it didn't.
* **History.** "It ran 47 times, failed twice, both in the Adzuna fetch, here are the
  logs" is a question cron cannot answer at all.
* **Backfills.** "Reprocess the last 30 days" is one command.
* **Visibility.** Someone who isn't you can see whether last night worked.

Those matter from roughly the point where a *second person* depends on the pipeline. At
one user on one laptop, cron is the right answer and Airflow is the learning exercise.

**Kafka vs a function call.** With one producer and one consumer, Kafka is strictly worse:
a broker to operate, a message format to version, and delivery semantics to reason about,
in exchange for nothing. Most "we use Kafka" portfolio projects are exactly this, and it
shows.

It earns its place only when **several independent consumers** react to the same event —
here a warehouse loader and a match notifier, with an embedder as an obvious third. The
test is: *if consumer B is broken, does the producer still work?* With direct calls, no.
With a broker, yes. That independence is what you are buying, and it is worth nothing
until you have more than one consumer.

**Spark vs pandas.** 152k rows is about 85MB. pandas handles that comfortably, in one
process, faster than Spark starts up. Spark is here so the code path is the one that still
works at 152 *million* — and so the caching, partitioning and native-expression decisions
are real decisions rather than things read about.

#### What that means for the numbers

The measured **57.1% Spark-over-MapReduce** result is real and reproducible, but it is
measured at a size where neither engine was under pressure. It demonstrates the
*direction* of the difference, not its magnitude at scale — where the gap widens
considerably, because MapReduce's per-step disk writes hurt more the more steps you have.

Quote it as "57% on my dataset", never as a general claim about the two engines.

#### How to say all this in an interview

> "Spark, Kafka and Airflow are not load-bearing at 152,000 rows — pandas and a cron job
> would do it. I built them because I wanted the decisions to be real ones: why cache,
> why a native expression instead of a UDF, why fan-out needs a broker. What IS
> load-bearing at any size is dbt's tests, the star schema, and Redis caching, and I'd
> keep all three in a project a tenth this size."

That answer is stronger than claiming you needed a cluster. It shows you can size a
solution to a problem, which is most of the actual job.


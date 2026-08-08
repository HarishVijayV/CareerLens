# The Project, In Plain English

## The pitch (30 seconds)

"I built a platform that ingests job postings at scale, processes them through a
Hadoop/Spark pipeline, models them into a dbt star schema, and puts a multi-agent AI
copilot on top that matches and tailors my resume against real postings. It's six FastAPI
microservices behind an API gateway with JWT auth, Redis caching and rate limiting, all
containerized. I benchmarked my Spark implementation against a raw MapReduce version of
the same aggregation — Spark came out 57% faster, and I can explain exactly why."

## The numbers to quote (all measured, none inherited)

| Claim | Actual measurement |
|---|---|
| Data processed | 200,000 rows → 195,959 after removing 4,041 duplicates |
| Spark vs MapReduce | 57.1% faster, 2.33× speedup (median of 3 runs each) |
| ML model | GBT R² = 0.911 vs LinearRegression baseline R² = 0.178 |
| Warehouse | 195,959 postings + 980,447 skill rows |
| Data quality | 17/17 dbt tests passing |

Raw output is committed: `pipeline/data/benchmark_results.json` and `model_metrics.json`.
"Here's the JSON and the script that produced it" is a far stronger position than a
number you can't reproduce.

## The longer version, layer by layer

**1. Data engineering.** Postings come from two sources: real ones from free public APIs
(Adzuna covering India and USA, Remotive for remote roles) and a synthetic generator that
scales the dataset to millions of rows with deliberately injected duplicates, malformed
salaries, and hiring seasonality — so the cleaning steps have real work to do. Raw data
lands untouched first (HDFS locally, S3-equivalent in cloud), because if a downstream bug
corrupts your clean data you need to be able to reprocess. PySpark then dedupes,
normalizes salaries, and computes aggregates.

**2. The benchmark.** The same skill-frequency aggregation is implemented twice: once as
a classic Hadoop Streaming MapReduce job (map → shuffle → reduce), once in Spark. The
benchmark runs both three times, reports medians, and asserts both engines produce
identical results — because a faster wrong answer is worthless. Spark wins by 57%, and
the reason is the interesting part: **MapReduce writes intermediate results to disk
between every stage; Spark keeps them in memory across a DAG.** Being able to explain
*that* is the difference between "I used Spark" and "I understand Spark".

**3. Warehouse + modeling.** Curated data loads into Postgres (fast reads for the app)
and can target Snowflake with the same dbt models. dbt builds a star schema — a fact
table of postings, dimensions for company and skill, and a bridge table for the
many-to-many between them — then runs 17 data-quality tests including referential
integrity. If the data is bad, the pipeline goes red there rather than silently serving
wrong numbers to a dashboard.

**4. Agentic AI.** A planner routes each request to one of five narrow specialists:
skill extractor, job matcher, resume tailor, market analyst, email classifier. Each gets
its own small tool allow-list, enforced at execution time — the email agent literally
cannot touch the resume, because it was never given that tool. The tool-calling loop is
written from scratch (~60 lines), and the same flow is re-implemented in LangGraph so
both approaches can be compared.

**5. Product plumbing.** JWT access tokens + rotating refresh tokens in httpOnly cookies,
bcrypt password hashing, RBAC, Redis-backed rate limiting, CORS, parameterized SQL
everywhere, and an API gateway as the single public entrypoint so no other service needs
to be internet-reachable.

## Answering the hard questions

**"Why Hadoop/MapReduce if Spark replaced it?"**
To prove I understand *why* Spark won, with my own benchmark rather than a claim. I can
walk through the disk-shuffle-per-stage versus in-memory-DAG difference and show the
timings.

**"Doesn't this already exist — Teal, Huntr, Simplify?"**
Yes. Novelty isn't the point; I designed and built every layer and can explain all of
them. That's what the interview is actually testing.

**"Is 200,000 rows really 'big data'?"**
No, and I wouldn't claim it is. It's the volume that fits on a laptop while exercising
genuinely distributed code paths — partitioned reads, shuffles, DAG execution. The same
job runs unchanged against a cluster; only the master URL changes. I'd rather quote a
number I measured than one I made up.

**"Why synthetic data at all?"**
Free job APIs return thousands of postings, not millions, and the sites that have
millions either charge or forbid scraping. So real data provides the messiness and
synthetic data provides the scale. Both paths run through the identical ETL.

**"Did you actually use it?"**
Answer honestly based on real usage. "I used it to track and tailor N applications" is a
perfectly good answer; so is "I built it to learn the stack end to end."

**"What was the hardest bug?"**
See [LESSONS.md](LESSONS.md) — 14 real ones. The best answer is probably the gateway
impersonation vulnerability (it forwarded a client-supplied identity header), or the
pipeline that worked once and broke on every re-run because dbt views depended on the
tables being replaced. Both have a clear cause, a clear fix, and a general lesson.

# CareerLens — Job Market & Career Intelligence Platform

A production-shaped system that ingests job-market data at scale, models it into a
warehouse, and puts a multi-agent AI copilot on top — built so every layer is something
you can explain, not just something that runs.

**In one sentence:** a Hadoop/Spark data pipeline feeding a dbt star schema, served by
FastAPI microservices behind an API gateway, with tool-calling AI agents and a Next.js
frontend.

> **Start here → [SETUP_CHECKLIST.md](SETUP_CHECKLIST.md)** — the short list of things
> only you can do (about 15 minutes; only one step is required).

## Verified results (measured, not claimed)

| What | Result |
|---|---|
| Rows processed | 200,000 → 195,959 after dedup (4,041 duplicates removed) |
| Spark vs MapReduce | **Spark 57.1% faster (2.33×)** — median of 3 runs each, same aggregation |
| MLlib salary model | GBT **R² = 0.911** vs LinearRegression baseline R² = 0.178 |
| Warehouse | 195,959 postings + 980,447 skill rows in Postgres |
| dbt | 5 models, **17/17 data-quality tests passing** |
| Tests | 24 Python tests passing |
| Airflow | DAG parses, 7 tasks, 0 import errors |

Raw numbers: `pipeline/data/benchmark_results.json`, `pipeline/data/model_metrics.json`.

## What actually runs

```
Next.js frontend  ──►  API Gateway  ──►  ┌─ auth-service      (JWT, cookies, RBAC, profiles)
  8 pages               (auth, CORS,     ├─ jobs-service      (search + 6 analytics endpoints)
                         rate limiting)  ├─ agent-service     (5 agents, tool calling, LangGraph)
                                         ├─ worker-service    (Celery background jobs)
                                         └─ notification-service
                                                │
                                    Postgres + Redis + Kafka
                                                ▲
                          ┌─────────────────────┴──────────────────────┐
                          │  DATA PIPELINE (runs independently)         │
                          │  job APIs + synthetic generator             │
                          │      → HDFS / local raw layer               │
                          │      → PySpark ETL (clean, dedupe, aggregate)│
                          │      → Spark MLlib (salary model)           │
                          │      → Postgres + Snowflake                 │
                          │      → dbt (star schema + 17 tests)         │
                          │  orchestrated by Airflow                    │
                          └────────────────────────────────────────────┘
```

## Quick start

```bash
cp infra/.env.example infra/.env      # then add your LLM key — see SETUP_CHECKLIST.md
cd infra && docker compose up -d      # Postgres, Redis, Kafka + 5 services
cd ../frontend && npm install && npm run dev
```

Open http://localhost:3000. Full instructions: [docs/LOCAL_SETUP.md](docs/LOCAL_SETUP.md).

Run the whole data pipeline in one command:

```bash
cd pipeline && python run_pipeline.py
```

## Documentation

| Doc | What it covers |
|---|---|
| [SETUP_CHECKLIST.md](SETUP_CHECKLIST.md) | **What you need to do** — API keys, first run |
| [docs/PROJECT_STORY.md](docs/PROJECT_STORY.md) | The pitch + how to answer "walk me through this" |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design, service map, request/data flow |
| [docs/DATA_ENGINEERING.md](docs/DATA_ENGINEERING.md) | Hadoop, Spark, MapReduce, Kafka, Airflow, dbt, Snowflake |
| [docs/AGENTIC_AI.md](docs/AGENTIC_AI.md) | The agent loop, sub-agents, tools, LangGraph comparison |
| [docs/AUTH_AND_SECURITY.md](docs/AUTH_AND_SECURITY.md) | JWT, refresh rotation, cookies, RBAC, rate limiting |
| [docs/LESSONS.md](docs/LESSONS.md) | **Real bugs hit while building, and what each one teaches** |
| [docs/ROADMAP.md](docs/ROADMAP.md) | What's done, what's next, cloud plan |

## Repo layout

```
services/            five FastAPI microservices, each with its own Dockerfile
  gateway/             single public entrypoint: auth middleware, CORS, rate limiting
  auth-service/        signup/login/refresh, bcrypt, JWT + rotating refresh tokens, profiles
  jobs-service/        job search + analytics over the dbt star schema, Redis cache-aside
  agent-service/       LLM provider abstraction, 5 agents, tool registry, LangGraph version
  worker-service/      Celery background jobs
  notification-service/
pipeline/            the data engineering side, independent of the web app
  ingestion/           job-board APIs (India+USA) + synthetic generator + warehouse loader
  spark_jobs/          PySpark ETL + MLlib model
  mapreduce_demo/      raw MapReduce job + benchmark vs Spark
  airflow/dags/        orchestration
  dbt/                 star schema models + data-quality tests
  run_pipeline.py      run the whole thing in one command
frontend/            Next.js app (8 pages, inline-SVG charts, no chart library)
tests/               24 tests covering security and pipeline logic
infra/               docker-compose (core + bigdata profile), env templates
```

## Tech

Python · FastAPI · PySpark · Hadoop/MapReduce · Kafka · Airflow · dbt · PostgreSQL ·
Snowflake · Redis · Celery · Docker · GitHub Actions · Next.js · React · TypeScript ·
Tailwind · LangGraph · Gemini/OpenAI/Anthropic/Fireworks

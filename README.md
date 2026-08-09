# CareerLens — Job Market & Career Intelligence Platform

A production-shaped system that ingests job-market data at scale, models it into a
warehouse, and puts a multi-agent AI copilot on top — built so every layer is something
you can explain, not just something that runs.

**In one sentence:** a Hadoop/Spark data pipeline feeding a dbt star schema, served by
FastAPI microservices behind an API gateway, with tool-calling AI agents and a Next.js
frontend.

> **New here? Read [HANDBOOK.md](HANDBOOK.md)** — every technology, why it is here, how it is
> used, and exactly what changes when you host it.
>
> **Start here → [SETUP_CHECKLIST.md](SETUP_CHECKLIST.md)** — the short list of things
> only you can do (about 15 minutes; only one step is required).

## Verified results (measured, not claimed)

| What | Result |
|---|---|
| Rows processed | 154,911 → **151,883** after dedup (3,028 duplicates removed) |
| Of which real | **4,911** live postings from Adzuna (India + USA); the rest generated for volume |
| Spark vs MapReduce | **Spark 57.1% faster (2.33×)** — median of 3 runs each, same aggregation |
| MLlib salary model | trained on REAL postings only: GBT **R² = 0.617** vs baseline **0.475** |
| Warehouse | 151,883 postings + **737,525** skill rows in Postgres |
| dbt | 5 models, **17/17 data-quality tests passing** |
| Tests | 33 Python tests passing |
| Airflow | DAG parses, 7 tasks, 0 import errors |
| Kubernetes | 14/14 pods running on a 3-node kind cluster, self-healing verified |

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
| [CHEATSHEET.md](CHEATSHEET.md) | **Start here if you're in a hurry** — the whole project in 5 minutes: pipeline, every tech in one line, the numbers, and what to say in an interview |
| [HANDBOOK.md](HANDBOOK.md) | **The complete guide** — every tech, why/how, hosting changes, interview answers |
| [DEPLOYMENT.md](DEPLOYMENT.md) | **Putting it online** — click-by-click from a fresh cloud account to a live HTTPS site, including every URL, redirect and cookie that must change |
| [SETUP_CHECKLIST.md](SETUP_CHECKLIST.md) | **What you need to do** — API keys, first run |
| [docs/PROJECT_STORY.md](docs/PROJECT_STORY.md) | The pitch + how to answer "walk me through this" |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design, service map, request/data flow |
| [docs/DATA_ENGINEERING.md](docs/DATA_ENGINEERING.md) | Hadoop, Spark, MapReduce, Kafka, Airflow, dbt, Snowflake |
| [docs/AGENTIC_AI.md](docs/AGENTIC_AI.md) | The agent loop, sub-agents, tools, LangGraph comparison |
| [docs/AUTH_AND_SECURITY.md](docs/AUTH_AND_SECURITY.md) | JWT, refresh rotation, cookies, RBAC, rate limiting |
| [docs/LESSONS.md](docs/LESSONS.md) | **Real bugs hit while building, and what each one teaches** |
| [docs/KUBERNETES.md](docs/KUBERNETES.md) | Running on Kubernetes — verified on a 3-node cluster |
| [docs/CLOUD_LEARNING_PLAN.md](docs/CLOUD_LEARNING_PLAN.md) | Staged plan to get this into a real cloud, free |
| [docs/ROADMAP.md](docs/ROADMAP.md) | What's done, what's next, cloud plan |

## Repo layout

```
services/            seven services, each with its own Dockerfile
  gateway/             single public entrypoint: auth middleware, CORS, rate limiting
  auth-service/        signup/login/refresh, bcrypt, JWT + rotating refresh tokens, profiles
  jobs-service/        job search + analytics over the dbt star schema, Redis cache-aside
  agent-service/       LLM provider abstraction, 5 agents, tool registry, LangGraph version
  worker-service/      Celery background jobs + Gmail sync + Kafka consumer
  notification-service/
  mcp-server/          MCP tools for external AI clients, network-isolated
pipeline/            the data engineering side, independent of the web app
  ingestion/           job-board APIs (India+USA) + synthetic generator + warehouse loader
  spark_jobs/          PySpark ETL + MLlib model
  mapreduce_demo/      raw MapReduce job + benchmark vs Spark
  airflow/dags/        orchestration
  dbt/                 star schema models + data-quality tests
  run_pipeline.py      run the whole thing in one command
frontend/            Next.js app (8 pages, inline-SVG charts, no chart library)
tests/               33 tests covering security, parsing and pipeline logic
infra/               docker-compose (core + bigdata profile), env templates
k8s/                 kind cluster config + Helm chart (verified on a 3-node cluster)
```

## Tech

Python · FastAPI · PySpark · Hadoop/MapReduce · Kafka · Airflow · dbt · PostgreSQL ·
Snowflake · Redis · Celery · Docker · GitHub Actions · Next.js · React · TypeScript ·
Tailwind · LangGraph · MCP · Kubernetes · Helm · Gemini/OpenAI/Anthropic/Fireworks

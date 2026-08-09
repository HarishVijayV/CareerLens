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
| Rows processed | 204,909 → **4,909** after dedup (4,041 duplicates removed) |
| Of which real | **4,909** live postings from Adzuna (India + USA); the rest generated for volume |
| Spark vs MapReduce | **Spark 57.1% faster (2.33×)** — median of 3 runs each, same aggregation |
| MLlib salary model | trained on REAL postings only: GBT **R² = 0.617** vs baseline **0.475** |
| Warehouse | 200,868 postings + **737,525** skill rows in Postgres |
| dbt | 5 models, **17/17 data-quality tests passing** |
| Tests | 33 Python tests passing |
| Job search | **2.0s → 0.52s** after indexing the analytics schema (3.8× faster) |
| Airflow | DAG parses, 7 tasks, 0 import errors |
| Kafka | **25 `posting.discovered` events published and read back** off the topic |
| Kubernetes | 14/14 pods running on a 3-node kind cluster, self-healing verified |

Raw numbers: `pipeline/data/benchmark_results.json`, `pipeline/data/model_metrics.json`.

## What actually runs

```
Next.js frontend  ──►  API Gateway  ──►  ┌─ auth-service      (JWT, cookies, RBAC, profiles)
  10 pages              (auth, CORS,     ├─ jobs-service      (search + 6 analytics endpoints)
                         rate limiting)  ├─ agent-service     (6 agents, tool calling, LangGraph)
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
cd infra && docker compose up -d      # 9 containers: Postgres, Redis + 6 services + frontend
cd ../frontend && npm install && npm run dev
```

Open http://localhost:3000. Full instructions: [docs/LOCAL_SETUP.md](docs/LOCAL_SETUP.md).

Run the whole data pipeline in one command:

```bash
cd pipeline && python run_pipeline.py
```

## What's optional, and what everything costs

Nine containers start by default. Kafka, Airflow, HDFS and the Kafka UI sit behind a
compose **profile**, so they only run when asked:

```bash
docker compose --profile bigdata up -d     # adds Kafka, Airflow, HDFS, Kafka UI (~1.2GB)
```

They are off by default for **RAM, not cost** — the two get conflated constantly:

| | Cost | Default | Why |
|---|---|---|---|
| Spark, Hadoop, dbt, Postgres, Redis, Parquet | free | **on** | open source, runs locally |
| Kafka, Airflow | free | **off** | ~600MB each on a laptop |
| Snowflake | **paid** ($400 trial, 30 days) | off | dbt falls back to Postgres automatically |
| Fireworks (LLM) | pay per call | on | fractions of a cent per question |
| Adzuna | free tier | on | daily quota, ample for one run a day |

**Neither Kafka nor Airflow is a dependency.** With Kafka down the ingest prints
`Kafka unavailable — events skipped` and finishes normally; an announcement failing must
never stop a data load. Without Airflow, `python run_pipeline.py` runs the identical seven
steps — Airflow calls those same scripts, it holds no logic of its own.

Once the profile is up:

| URL | What |
|---|---|
| http://localhost:3000 | the app |
| http://localhost:8085 | Kafka UI — topics, partitions, message contents |
| http://localhost:8081 | Adminer — browse the database |

Kafka's own port (`29092`) speaks a binary protocol, not HTTP — a browser gets
`ERR_EMPTY_RESPONSE` there, which is expected. That is what the UI is for.

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
  agent-service/       LLM provider abstraction, 6 agents, tool registry, LangGraph version
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
frontend/            Next.js app (10 pages, inline-SVG charts, no chart library)
tests/               33 tests covering security, parsing and pipeline logic
infra/               docker-compose (core + bigdata profile), env templates
k8s/                 kind cluster config + Helm chart (verified on a 3-node cluster)
```

## Tech

Python · FastAPI · PySpark · Hadoop/MapReduce · Kafka · Airflow · dbt · PostgreSQL ·
Snowflake · Redis · Celery · Docker · GitHub Actions · Next.js · React · TypeScript ·
Tailwind · LangGraph · MCP · Kubernetes · Helm · Gemini/OpenAI/Anthropic/Fireworks

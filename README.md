# CareerLens — Job Market & Career Intelligence Platform

CareerLens is a full production-style system that helps a job-seeker (you) collect real
job-market data at scale, understand it, and act on it — with a team of AI agents doing the
grunt work. It's built to look and behave like a real company's platform, not a tutorial app,
so every piece of it is something you can defend in an interview.

**In one sentence:** a data engineering pipeline that ingests job-market data at scale, a
warehouse + analytics layer that makes sense of it, and a multi-agent AI copilot on top that
matches your resume to jobs, tailors it, tracks your applications (including your inbox), and
tells you what's actually working.

> Rename freely — "CareerLens" is just a placeholder product name.

## Why this project exists

Read [docs/PROJECT_STORY.md](docs/PROJECT_STORY.md) for the plain-English pitch, and
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for how every piece fits together.

## Documentation map

| Doc | What it covers |
|---|---|
| [docs/PROJECT_STORY.md](docs/PROJECT_STORY.md) | The elevator pitch + how to answer "walk me through this project" |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Full system design (HLD), service map, data flow diagrams |
| [docs/DATA_ENGINEERING.md](docs/DATA_ENGINEERING.md) | Hadoop/HDFS, PySpark, MapReduce benchmark, Kafka, Airflow, dbt, Snowflake — what each does and why it's there |
| [docs/AGENTIC_AI.md](docs/AGENTIC_AI.md) | Agent/sub-agent design, tool-calling loop, LangGraph version, LLM provider abstraction |
| [docs/AUTH_AND_SECURITY.md](docs/AUTH_AND_SECURITY.md) | JWT, sessions, cookies, refresh tokens, RBAC, rate limiting, CORS/CSRF |
| [docs/LOCAL_SETUP.md](docs/LOCAL_SETUP.md) | How to run everything on your machine |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Phased build plan — local first, cloud a month later |

## Repo layout

```
services/            # microservices (each is its own FastAPI app + Dockerfile)
  gateway/            # API gateway / main backend — entrypoint for the frontend
  auth-service/        # signup/login, JWT + sessions + cookies, RBAC
  agent-service/        # the multi-agent AI copilot (orchestrator + sub-agents)
  worker-service/        # background jobs (Celery) — scraping, email sync, embeddings
  notification-service/   # emails/alerts to the user
pipeline/            # the data engineering side, independent of the web app
  ingestion/           # scrapers / public job APIs + synthetic data generator
  spark_jobs/           # PySpark ETL + MLlib model training
  mapreduce_demo/        # one raw MapReduce job + benchmark vs Spark
  airflow/dags/          # orchestration DAGs tying the pipeline together
  dbt/                # transformation + data quality tests (Snowflake/Postgres)
  ml/                 # model training/eval scripts (outside Spark, for smaller models)
frontend/            # Next.js app
infra/              # docker-compose, env templates
```

## Quick start

See [docs/LOCAL_SETUP.md](docs/LOCAL_SETUP.md). Short version:

```bash
cp infra/.env.example infra/.env
docker compose -f infra/docker-compose.yml up -d --build
```

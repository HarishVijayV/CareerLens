# Roadmap — Phased Build Plan

Local-first. Cloud is a later phase, deliberately — get one machine working end to end before
paying for infrastructure or fighting cloud IAM permissions.

## Phase 0 — Scaffold (this session)
- Repo structure, all docs, docker-compose skeleton, empty-but-runnable services, pipeline
  script skeletons, frontend skeleton. Goal: `docker compose up` boots without crashing.

## Phase 1 — Auth + Gateway, for real
- Auth Service: signup/login/refresh/logout fully working against Postgres, bcrypt hashing,
  JWT + refresh cookie flow, RBAC.
- Gateway: routes to Auth Service, auth middleware, CORS, rate limiting via Redis.
- Frontend: signup/login pages, protected dashboard shell.
- **Checkpoint:** you can register, log in, see a protected page, get logged out on expiry,
  refresh silently.

## Phase 2 — Data pipeline v1 (small scale)
- `pipeline/ingestion`: synthetic generator producing ~100k rows first (prove correctness
  before scaling up), plus one real job API integration.
- `pipeline/spark_jobs/etl_clean_jobs.py` running locally against those files (skip HDFS at
  first — local filesystem is fine to prove the Spark logic).
- Curated output lands in Postgres. A simple dashboard page lists jobs.
- **Checkpoint:** real (or synthetic) job postings are queryable from the app.

## Phase 3 — Scale the pipeline up + add HDFS/Kafka
- Bring up single-node Hadoop via Docker; point the Spark job at HDFS instead of local files.
- Scale the generator to millions of rows.
- Add the MapReduce benchmark job and record real before/after numbers.
- Wire Kafka: scraper publishes `new-posting-scraped`, a consumer reacts.
- **Checkpoint:** you have your own "15M+ records, X% faster with Spark" numbers, measured.

## Phase 4 — Orchestration + warehouse
- Airflow DAG scheduling the whole pipeline.
- dbt project: star schema models + data-quality tests, targeting Postgres locally and
  Snowflake (free trial) for the warehouse layer.
- **Checkpoint:** one Airflow DAG run takes raw data all the way to warehouse tables, with
  passing dbt tests.

## Phase 5 — Agentic AI copilot
- LLM provider abstraction + hand-rolled orchestrator with 2-3 sub-agents (skill extractor,
  resume matcher, resume tailor) against real data from Phase 2-4.
- LangGraph re-implementation of the same agents.
- **Checkpoint:** you can ask "match my resume against job X" and get a real, data-backed
  answer.

## Phase 6 — Gmail integration + application tracking
- Google OAuth, Gmail read-only sync in the Worker Service, email-classifier agent, funnel
  analytics (insight agent), resume-version A/B tracking.
- **Checkpoint:** the app can tell you your real application funnel and which resume version
  performs better.

## Phase 7 — DevOps hardening
- GitHub Actions: lint/test → build images → push to GHCR → (later) deploy.
- Basic Prometheus + Grafana for service health/metrics.
- **Checkpoint:** a push to `main` automatically produces a tested, versioned image.

## Phase 8 — Cloud (≈ one month after local is solid)
- Pick one provider (start with the one you're most likely to be asked about — AWS is the
  safest default for job interviews). Move storage to S3, managed Postgres (RDS), managed
  Kubernetes (EKS), Spark to EMR or keep on a VM to start cheaply.
- Kubernetes: Helm charts, Ingress, Secrets/ConfigMaps for what's currently `.env`.
- **Checkpoint:** the same system runs in the cloud with no pipeline-logic changes — only
  infrastructure changes, which is the whole point of Phase 0-7 being built the way they are.

## Ground rule for every phase

Don't move to the next phase until you can explain the current one out loud, unaided, in under
two minutes — that's the actual success metric for a resume project, not "does it run."

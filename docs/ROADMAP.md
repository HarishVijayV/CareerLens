# Roadmap — What's Done, What's Next

Local-first by design: get one machine working end to end before paying for cloud
infrastructure or fighting IAM.

---

## DONE — Phase 0: Scaffold
Repo structure, all docs, docker-compose, six services, pipeline scripts, frontend.

## DONE — Phase 1: Auth + Gateway
- Signup, login, logout, `/me`, and **refresh with token rotation** — all working
- bcrypt password hashing (with the 72-byte limit handled), JWT access tokens,
  opaque refresh tokens stored hashed, httpOnly `SameSite=Lax` cookies
- Gateway: auth middleware, Redis rate limiting, CORS, request logging, service proxying
- RBAC dependency (`require_role`)
- Frontend: signup/login/dashboard, session handling
- **Verified:** full flow tested through the gateway; CORS preflight + credentialed
  cookies confirmed from the frontend origin. 24 tests pass.

## DONE — Phase 2: Data pipeline
- Synthetic generator (deterministic, injects duplicates + messy salaries + seasonality)
- Real job-board ingestion — Adzuna (India + USA), Remotive, with a title-based relevance
  filter added after the API returned unrelated roles
- PySpark ETL: dedupe, salary cleaning via native SQL, 4 aggregate tables, skills bridge table
- **Verified:** 205,397 rows → 201,356 after removing 4,134 duplicates (4,907 of them live postings)

## DONE — Phase 3: Scale + benchmark
- Hadoop Streaming mapper/reducer, and the same aggregation in Spark
- Benchmark runs both N times and reports medians, with a correctness assertion that both
  engines agree
- **Verified: Spark 57.1% faster (2.33×)** — your own measured number, not an inherited claim
- Kafka is running in compose; event publishing is wired into the worker service but the
  pipeline is currently batch-driven

## DONE — Phase 4: Orchestration + warehouse
- Airflow DAG: 7 tasks, correct fan-in, retries, **validated — 0 import errors**
- dbt: staging + star schema (fact, 2 dims, bridge), custom `accepted_range` generic test
  written from scratch instead of pulling in dbt_utils
- **Verified: 5 models built, 17/17 data-quality tests pass** against live Postgres
- Snowflake target configured in `profiles.yml` (same models, different target)

## DONE — Phase 5: Agentic AI
- Tool-calling loop written from scratch, returning a full trace of every call
- 5 agents, each with an explicit tool allow-list enforced at execution time
- Deterministic routing *and* LLM routing, with a documented reason for both
- Provider abstraction: Gemini / Fireworks / OpenAI / Anthropic, swappable by config
- LangGraph implementation of the same flow, for the framework-vs-scratch comparison
- `/copilot` page renders every tool call so the agent is visibly real
- **Needs your API key to run** — see [SETUP_CHECKLIST.md](../SETUP_CHECKLIST.md)

## DONE — Phase 7 (partial): CI
GitHub Actions: lint → test → frontend build → build all six images. Publish job written
but disabled until a registry exists.

---

## NEXT — Phase 6: Gmail + application tracking
The remaining product feature. Needs Google OAuth credentials (free).

- Google OAuth flow, Gmail readonly scope, encrypted token storage
- Worker task polls the inbox; the `email_classifier` agent (already written) labels each
  message applied / rejected / interview / offer
- `fact_application` table + funnel analytics: applied → interview → offer
- Resume-version A/B: which version actually gets more replies
- Resume tailoring to LaTeX + PDF compile via a Dockerized `texlive` image

## NEXT — Phase 8: Cloud (~1 month out)
Nothing in the pipeline logic changes — only where storage and compute physically run.

| Local | AWS | Azure | OCI |
|---|---|---|---|
| HDFS / local FS | S3 | Blob Storage | Object Storage |
| Local Spark | EMR / Glue | HDInsight / Synapse | Data Flow |
| Docker Compose | ECS / EKS | AKS | OKE |
| Self-hosted Postgres | RDS | Azure DB for PostgreSQL | OCI PostgreSQL |
| Self-hosted Kafka | MSK | Event Hubs | OCI Streaming |

Then: Kubernetes manifests → Helm charts → Ingress → Secrets/ConfigMaps replacing `.env`
→ Prometheus + Grafana → enable the CI publish job.

---

## Ground rule

Don't move on until you can explain the current phase out loud, unaided, in under two
minutes. For a portfolio project that's the actual success metric — not "does it run".
[docs/LESSONS.md](LESSONS.md) is the best material for this: 14 real bugs, each with what
it teaches.

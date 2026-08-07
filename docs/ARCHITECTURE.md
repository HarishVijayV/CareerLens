# Architecture (High-Level Design)

## System diagram

```
                         ┌─────────────────────┐
                         │   Next.js Frontend    │  (React, cookies for session)
                         └──────────┬───────────┘
                                    │ HTTPS
                         ┌──────────▼───────────┐
                         │      Gateway          │  FastAPI — single entrypoint
                         │  (routing, middleware, │  for the frontend. Handles
                         │  rate limiting, CORS)  │  cross-cutting concerns once,
                         └──────────┬───────────┘  instead of in every service.
              ┌─────────────┬───────┼───────────┬─────────────┐
              ▼             ▼       ▼           ▼             ▼
      ┌───────────┐ ┌─────────────┐ ┌──────────────┐ ┌──────────────────┐
      │   Auth    │ │   Agent     │ │   Worker     │ │   Notification    │
      │  Service  │ │  Service    │ │  Service     │ │   Service         │
      │ (JWT,     │ │ (orchestrator│ │ (Celery —    │ │ (email/alerts)    │
      │  sessions,│ │ + sub-agents,│ │  scraping,   │ │                    │
      │  RBAC)    │ │  LLM calls)  │ │  Gmail sync, │ │                    │
      └─────┬─────┘ └──────┬──────┘ │  embeddings) │ └────────┬───────────┘
            │              │        └──────┬───────┘          │
            └──────────────┴───────┬───────┴──────────────────┘
                                   ▼
                     ┌─────────────────────────────┐
                     │   Postgres   +   Redis        │  serving layer + cache/session store
                     └─────────────┬───────────────┘
                                   │
                                   ▼
                     ┌─────────────────────────────┐
                     │        Kafka (events)          │  new-posting / new-email topics
                     └─────────────┬───────────────┘
                                   │
                     ┌─────────────▼───────────────┐
                     │   Data Engineering Pipeline    │
                     │  HDFS → PySpark ETL/MLlib →     │  see DATA_ENGINEERING.md
                     │  Airflow (orchestration) →      │
                     │  Postgres + Snowflake            │
                     └─────────────────────────────┘
```

## Why microservices, and why these five

Splitting into services isn't cargo-culting — each one has a genuinely different reason to
scale or fail independently:

- **Gateway** — the only service the browser ever talks to. Centralizes auth-token
  verification, CORS, rate limiting, request logging. If this is the only thing exposed to the
  internet, every other service can stay on a private network — that's a real security
  pattern, not just tidiness.
- **Auth Service** — owns user identity end to end (signup, login, password hashing, JWT
  issuance, refresh tokens, session cookies, RBAC checks). Isolating it means a bug in, say,
  the agent service can never leak into how passwords are handled.
  See [AUTH_AND_SECURITY.md](AUTH_AND_SECURITY.md).
- **Agent Service** — the AI brain. Calls out to an LLM provider, which is slow and sometimes
  expensive/rate-limited — keeping it separate means a slow agent call never blocks login or
  page loads elsewhere. See [AGENTIC_AI.md](AGENTIC_AI.md).
- **Worker Service** — anything long-running or scheduled (scraping job boards, polling Gmail,
  generating embeddings) runs here asynchronously via Celery, off the request/response path.
  A user request should never block on a 30-second scrape.
- **Notification Service** — sends emails/alerts (e.g. "3 new jobs match your resume"). Kept
  separate so a flaky email provider never affects the core app.

## Request flow example: "tailor my resume for this job"

1. Frontend sends the request with an httpOnly session cookie to the **Gateway**.
2. Gateway's auth middleware validates the JWT (from the cookie) — no valid token, no
   forwarding. Rate-limit middleware checks Redis for this user's recent request count.
3. Gateway forwards to **Agent Service** with the verified user ID attached in a header (the
   downstream services trust the gateway, not the raw cookie).
4. Agent Service's **orchestrator** parses the intent, calls the **skill-extractor** sub-agent
   on the job description, then the **resume-tailor** sub-agent with your stored resume +
   extracted skills.
5. Result is cached in Redis (same job + same resume version → don't re-call the LLM), written
   to Postgres, and returned.
6. A Kafka event `resume.tailored` is published; the Worker Service picks it up to
   re-render/compile the LaTeX resume to PDF in the background.

## Data flow: pipeline side (independent of the live app)

```
Public job APIs / synthetic generator
        │
        ▼
   Kafka topic: new-posting-scraped
        │
        ▼
   HDFS (raw landing zone)
        │
        ▼
   PySpark ETL  ──►  MapReduce benchmark job (same aggregation, for comparison)
        │
        ▼
   Spark MLlib (salary prediction / posting clustering)
        │
        ▼
   curated tables  ──►  Postgres (app reads this)  +  Snowflake (BI/analytics)
        │
        ▼
   Airflow DAG schedules and wires every step above; dbt runs transformations
   + data-quality tests on top of the warehouse tables.
```

## Tech choices, one line each

| Layer | Choice | Why |
|---|---|---|
| Frontend | Next.js (React) | SSR where useful, easy cookie-based auth handling |
| API layer | FastAPI (Python) | async, typed, auto OpenAPI docs, matches the DE/ML stack language |
| Auth | JWT (access) + refresh token + httpOnly session cookie | industry-standard combo, explained in AUTH_AND_SECURITY.md |
| Cache/session store | Redis | de-facto standard, also backs Celery and rate limiting |
| Primary DB | PostgreSQL | relational, strong consistency for user/app data |
| Warehouse | Snowflake | cloud-native analytics warehouse, huge in real DE job specs |
| Event bus | Kafka | real-time, decouples services, standard DE/distributed-systems skill |
| Big data lake + processing | HDFS + PySpark | direct evolution of the original resume bullet |
| Orchestration (pipeline) | Airflow | industry standard for scheduling DAGs |
| Transform + data quality | dbt | SQL-based, testable, widely required |
| Background jobs (app-side) | Celery + Redis | standard Python async task pattern |
| Containers | Docker + Docker Compose (local) → Kubernetes (later) | portable across AWS/Azure/OCI |
| CI/CD | GitHub Actions | build → test → image → registry → deploy |

## Cloud portability (why local choices map cleanly later)

| Local | AWS | Azure | OCI |
|---|---|---|---|
| HDFS / MinIO | S3 | Blob Storage | Object Storage |
| Local Spark | EMR / Glue | HDInsight / Synapse | Data Flow |
| Docker Compose | ECS/EKS | AKS | OKE |
| Self-hosted Postgres | RDS | Azure Database for PostgreSQL | OCI PostgreSQL |
| Self-hosted Kafka | MSK | Event Hubs | OCI Streaming |

Nothing in the pipeline logic needs to change to move providers — only where storage/compute
physically runs. That's the whole point of building it this way.

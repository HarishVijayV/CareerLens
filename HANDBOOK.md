# CareerLens — The Complete Handbook

**Read this first.** Everything about this project: what every technology is, why it's
here, how it's used, what breaks without it, and exactly what changes when you host it.

Written so someone who clones this repo cold can understand the whole system — and so
*you* can revise it before an interview.

---

## Table of contents

1. [What this project is](#1-what-this-project-is)
2. [The 60-second mental model](#2-the-60-second-mental-model)
3. [Every technology — what, why, how](#3-every-technology--what-why-how)
4. [How a request actually flows](#4-how-a-request-actually-flows)
5. [How data actually flows](#5-how-data-actually-flows)
6. [The AI layer explained](#6-the-ai-layer-explained)
7. [Security decisions](#7-security-decisions)
8. [Running it locally](#8-running-it-locally)
9. [Every credential and what breaks without it](#9-every-credential-and-what-breaks-without-it)
10. [HOSTING: everything that must change](#10-hosting-everything-that-must-change)
11. [Real bugs and what they taught](#11-real-bugs-and-what-they-taught)
12. [What's deliberately NOT here](#12-whats-deliberately-not-here)
13. [Interview answers](#13-interview-answers)

---

## 1. What this project is

A job-seeker's tool, built the way a company would build it.

You give it your resume and what you're looking for. It ingests job postings at scale,
processes them through a distributed pipeline into a modelled warehouse, and puts AI
agents on top that find matching roles, score your resume against them, rewrite it, and
track every application by reading your inbox.

**The real reason it exists:** to be a portfolio project where every layer is defensible —
data engineering, backend, AI, and infrastructure — rather than a tutorial follow-along.

### Measured results (not claims)

| What | Result |
|---|---|
| Rows processed | 200,000 → 195,959 after removing 4,041 duplicates |
| Spark vs MapReduce | **57.1% faster (2.33×)** — median of 3 runs each, same aggregation |
| ML model | GBT R² = 0.911 vs LinearRegression baseline R² = 0.178 |
| Warehouse | 195,959 postings + 980,447 skill rows |
| Data quality | 17/17 dbt tests passing |
| Tests | 33 Python tests |
| Kubernetes | 14/14 pods, self-healing verified by killing a pod mid-request |

Raw output committed in `pipeline/data/*.json` — you can reproduce every number.

---

## 2. The 60-second mental model

Three independent systems that meet at a database:

```
   ┌──────────────────────────────────────────────────────────┐
   │ 1. THE PIPELINE  (batch, runs on a schedule)              │
   │    job APIs + generator → Spark → ML → dbt → warehouse     │
   └───────────────────────────┬──────────────────────────────┘
                               │ writes curated data
                               ▼
                    ┌──────────────────────┐
                    │  PostgreSQL + Redis   │
                    └──────────┬───────────┘
                               │ reads
   ┌───────────────────────────┴──────────────────────────────┐
   │ 2. THE APP  (request/response)                            │
   │    Next.js → Gateway → auth / jobs / agent / worker        │
   └───────────────────────────┬──────────────────────────────┘
                               │
   ┌───────────────────────────┴──────────────────────────────┐
   │ 3. THE AI LAYER  (agents calling tools)                   │
   │    planner → specialist agent → tools → warehouse data     │
   └──────────────────────────────────────────────────────────┘
```

**The key separation:** the AI layer never touches raw data. It only reads curated data
that has already passed dbt's quality tests. That's a deliberate answer to "how do you
stop an LLM hallucinating numbers" — you don't let it near unvalidated data.

---

## 3. Every technology — what, why, how

### Data engineering

| Tech | What it is | Why it's here | How it's used |
|---|---|---|---|
| **PySpark** | Distributed data processing | Processes more data than one machine's RAM holds; partitions work across cores/nodes | `pipeline/spark_jobs/etl_clean_jobs.py` — dedupe, clean salaries, aggregate 200K rows |
| **Hadoop / MapReduce** | The older distributed model | To *prove* why Spark won, with a measured benchmark rather than a claim | `pipeline/mapreduce_demo/` — same aggregation both ways, timed |
| **Spark MLlib** | ML on Spark | Scores every posting against what its role typically pays | `mllib_salary_model.py` — GBT + a LinearRegression baseline |
| **Kafka** | Event streaming | Fan-out: one `posting.discovered` event, several independent consumers | `pipeline/events.py` produces; `worker-service/app/consumers/` consumes |
| **Airflow** | Workflow orchestration | Schedules the pipeline as a DAG with retries — "here's the DAG" beats "I ran some scripts" | `pipeline/airflow/dags/job_pipeline_dag.py`, 7 tasks |
| **dbt** | SQL transformation + testing | Builds the star schema and **fails the run** if data is bad | `pipeline/dbt/` — 5 models, 17 tests |
| **PostgreSQL** | Relational database | Serving layer: fast reads for the app and agents | app data + `analytics.*` star schema |
| **Snowflake** | Cloud data warehouse | Historical/BI analytics; same dbt models, different target | `profiles.yml` target `warehouse` — auto-falls back to Postgres |
| **Redis** | In-memory store | Cache, rate limiting, Celery broker — three jobs, one dependency | cache-aside in `jobs-service` |

**Why both real AND synthetic data:** free job APIs return thousands of postings, not
millions. Sites with millions either charge or forbid scraping. So **real data provides
the messiness** (missing fields, inconsistent formats) and **synthetic data provides the
scale**. Both go through the identical ETL.

### Backend

| Tech | What it is | Why it's here |
|---|---|---|
| **FastAPI** | Async Python web framework | Typed, auto-generates OpenAPI docs, same language as the data stack |
| **API Gateway** | Single public entrypoint | Verify JWT once at the edge; every other service stays private |
| **JWT** | Signed stateless token | Fast auth check without a DB lookup per request |
| **Refresh tokens** | Opaque, stored hashed | JWTs can't be revoked early — refresh tokens can |
| **bcrypt** | Password hashing | Deliberately slow, salted per password |
| **Celery** | Distributed task queue | Slow work (inbox sync, scraping) off the request path |
| **SQLAlchemy** | ORM | Parameterized queries — SQL injection impossible by construction |

### AI

| Tech | Why it's here |
|---|---|
| **Tool-calling loop (from scratch)** | ~60 lines in `agents/base.py`. Proves you understand the mechanism, not just a library |
| **LangGraph** | The same flow as an explicit graph — so you can compare scratch vs framework |
| **Provider abstraction** | Fireworks / Gemini / OpenAI / Anthropic swappable by one config line |
| **MCP server** | Exposes job-market data to *external* AI clients — a genuinely different capability |

### Frontend

Next.js 16 (App Router), React 19, TypeScript, Tailwind v4. Charts are **inline SVG, no
charting library** — every visual decision is explainable, and there's no black box.

### Infrastructure

| Tech | Why |
|---|---|
| **Docker** | Same environment everywhere |
| **Docker Compose** | Whole stack, one command, auto-restarts |
| **Kubernetes** | Self-healing, rolling deploys, horizontal scaling |
| **Helm** | One chart, many environments — the values file *is* the environment contract |
| **kind** | Real Kubernetes locally, so you learn k8s without also fighting cloud IAM |
| **GitHub Actions** | test → build → publish, each gate protecting the next |
| **GHCR** | Image registry, free for public repos |

---

## 4. How a request actually flows

**"Tailor my resume for job X"**

1. Browser sends the request with httpOnly cookies to the **Gateway**
   (`credentials: "include"` — without it the browser won't attach cookies cross-origin)
2. Gateway middleware, in order: **logging** → **auth** (verify JWT signature + expiry) →
   **rate limit** (Redis sliding window, keyed by the user id auth just established)
3. Gateway **strips any client-supplied `X-User-Id`** and sets its own from the verified
   token. ← security-critical; see §7
4. Forwards to **agent-service**, which routes to `resume_tailor`
5. Agent runs the tool loop: `get_resume` → `get_job` → rewrite → `save_tailored_resume`
6. Response includes **every tool call it made**, rendered in the UI

**On a 401:** the frontend silently calls `/auth/refresh` once and replays the request.
One shared in-flight promise, because refresh *rotates* the token — parallel refreshes
would invalidate each other and log you out precisely *because* the security works.

---

## 5. How data actually flows

```
job APIs (Adzuna IN+US, Remotive)  +  synthetic generator
                    ↓
        raw landing zone (immutable — reprocessable)
                    ↓
        PySpark ETL: dedupe, clean salaries, extract skills
                    ↓  (also emits a posting_skills bridge table)
        Spark MLlib: batch-score every posting vs market rate
                    ↓
        load into Postgres  (COPY, not INSERT — minutes vs seconds)
                    ↓
        dbt: staging → star schema → 17 quality tests
                    ↓
        analytics.fact_job_posting + dims  ← the app reads ONLY this
```

**Star schema:** `fact_job_posting` with `dim_company`, `dim_skill`, and
`bridge_posting_skill` for the many-to-many.

**Why a bridge table and not an array column:** array types differ across engines
(Postgres `unnest` vs Snowflake `FLATTEN`). Bridge rows are plain SQL that works
identically everywhere — the same portability reasoning as the rest of the chart.

Run it all: `cd pipeline && python run_pipeline.py`

---

## 6. The AI layer explained

**An agent is a loop.** That's it:

```
1. Send the LLM the conversation + the tools it may call
2. It replies with either an answer OR a request to call a tool
3. If a tool: run the real Python function, get a real result
4. Feed the result back, go to 1
5. Stop when it answers instead of calling another tool
```

**The model never executes anything.** It only *asks* for a tool by name. Our code decides
whether that's allowed and runs it. "The model requests, your code decides" is the whole
of agent security.

### The five agents and their permissions

| Agent | Tools it may call | Notably cannot |
|---|---|---|
| `skill_extractor` | none (pure extraction) | — |
| `job_matcher` | `get_profile`, `search_jobs`, `get_job` | write anything |
| `resume_tailor` | `get_resume`, `get_resume_latex`, `get_job`, `save_tailored_resume` | read email |
| `market_analyst` | `get_market_analytics`, `search_jobs` | see personal data |
| `email_classifier` | none (given the email text) | **touch your resume** |

Least privilege is enforced **at execution time**, not just in the prompt — restricting
what a model *sees* is a soft boundary; checking again when the tool runs is the hard one.

### Why agents make cost matter

One user question = **3–6 LLM calls** (plan → tool → read → answer). Inbox sync is **one
call per email**. That's why the provider defaults to Fireworks: a per-minute-limited free
tier stalls an agent *mid-loop* rather than failing cleanly.

### MCP — and how to actually use it

MCP (Model Context Protocol) publishes tools over a standard protocol so **any** AI client
can discover and call them — unlike a REST API, which needs custom integration code per
client.

**Use it right now:**

- **In Claude Code:** `.mcp.json` in the repo root is already configured. Open this folder
  in Claude Code with the stack running and the tools appear. Ask *"which skills pay above
  average?"* and it queries your warehouse.
- **In Claude Desktop:** add to its config:
  ```json
  { "mcpServers": { "careerlens": { "type": "http", "url": "http://localhost:8005/mcp" } } }
  ```
- **Verify by hand:**
  ```bash
  curl -X POST http://localhost:8005/mcp \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
  ```

**8 tools exposed:** `search_jobs`, `job_details`, `market_overview`, `top_skills`,
`skill_premium`, `salary_by_seniority`, `salary_by_region`, `hiring_seasonality`.

**Zero personal data exposed**, and that's enforced by network isolation — the MCP
container runs on a Docker network shared only with `jobs-service`; `auth-service` doesn't
even resolve from it.

---

## 7. Security decisions

| Concern | How it's handled |
|---|---|
| Passwords | bcrypt + per-password salt; SHA-256 pre-hash so bcrypt's 72-byte limit can't silently truncate |
| Sessions | 15-min JWT + 7-day refresh token, **rotated** on every use |
| Token storage | httpOnly cookies — JavaScript cannot read them, so XSS can't steal them |
| Identity forwarding | Gateway **strips** client `X-User-Id` before setting its own |
| SQL injection | Bound parameters everywhere; never string-formatted SQL |
| Rate limiting | Redis sliding window at the gateway |
| CORS | Explicit allow-list of one origin |
| Third-party tokens | Google refresh tokens **encrypted** (Fernet) at rest |
| Secret leakage | Pre-commit hook blocks key-shaped strings and any `.env` |
| MCP exposure | Separate service, isolated network, aggregate data only |

**The one worth memorising:** *"auth-service trusts the `X-User-Id` header — which is safe
only because exactly one component can write it. The gateway strips whatever the client
sent and sets it from the verified JWT. Trusted-header auth is a good pattern behind a
gateway and a critical vulnerability without one."*

---

## 8. Running it locally

### Prerequisites
Docker Desktop, Python 3.11+, Node 18+, Java 17 (Spark), and on Windows `winutils.exe`.

### The whole app
```bash
cp infra/.env.example infra/.env       # add FIREWORKS_API_KEY
cd infra && docker compose up -d       # everything, including the frontend
```
→ http://localhost:3000

Every service has `restart: unless-stopped`, so starting Docker Desktop brings the whole
stack back with no command at all.

### The data pipeline
```bash
cd pipeline
pip install -r requirements.txt
python run_pipeline.py                 # generate → fetch → Spark → ML → load → dbt
python run_pipeline.py --benchmark     # include the MapReduce comparison
```

### Kubernetes
See [docs/KUBERNETES.md](docs/KUBERNETES.md). Short version:
```bash
kind create cluster --config k8s/kind-config.yaml
# install + pin ingress controller (commands in kind-config.yaml)
# build + kind load images
kubectl create secret generic careerlens-secrets --from-literal=...
helm install careerlens k8s/helm/careerlens
```

### Check everything
```bash
python check_setup.py     # services, auth, warehouse, credentials, agents, resume
```

---

## 9. Every credential and what breaks without it

| Credential | Cost | Required? | Without it |
|---|---|---|---|
| `FIREWORKS_API_KEY` | trial credits | for AI | Copilot returns a clear 502; everything else works |
| `GEMINI_API_KEY` | **free forever** (rate-limited) | no | fallback when Fireworks credits run out |
| `ADZUNA_APP_ID/KEY` | free | no | only Remotive fetched — no India/USA targeting |
| `GOOGLE_CLIENT_ID/SECRET` | free | no | Applications page shows "not configured"; manual entry still works |
| `TOKEN_ENCRYPTION_KEY` | — | no | falls back to `JWT_SECRET_KEY` (couples two secrets — fine for dev only) |
| `JWT_SECRET_KEY` | — | **yes** | already generated |
| Snowflake (5 vars) | 30-day trial | no | **auto-falls back to Postgres**, same models and tests |

Full walkthrough: [docs/CREDENTIALS.md](docs/CREDENTIALS.md)

---

## 10. HOSTING: everything that must change

**This is the section people get wrong.** Local works; hosting breaks in a dozen small
ways. Here is every one.

### 10.1 Google OAuth redirect URI ← the one that bites first

Google matches redirect URIs **character for character**.

1. Google Cloud Console → **APIs & Services → Credentials** → your OAuth client
2. Under **Authorized redirect URIs**, **add** (keep localhost so local dev still works):
   ```
   https://yourdomain.com/api/auth/google/callback
   ```
3. ⚠️ **HTTPS is mandatory** for any non-localhost redirect URI. Plain `http://` is
   rejected outright.
4. Update `.env`:
   ```
   GOOGLE_REDIRECT_URI=https://yourdomain.com/api/auth/google/callback
   FRONTEND_URL=https://yourdomain.com
   ```

**Also:** while the app stays in Google's "Testing" mode, only accounts you add as test
users can connect Gmail (100 max). Publishing needs verification, and `gmail.readonly` is
a **restricted** scope — that means a privacy policy, demo video, and a paid third-party
security assessment. Not worth it for a portfolio project. Demo it on your own account.

### 10.2 Cookies — three settings that must all change

```bash
COOKIE_SECURE=true            # cookies only sent over HTTPS
COOKIE_DOMAIN=yourdomain.com  # not "localhost"
```
And if the frontend and API end up on **different domains**, `SameSite=Lax` stops sending
cookies on cross-site requests — you'd need `SameSite=None; Secure` **and** a CSRF token.
Simplest fix: serve both from one domain (`/` and `/api`), which is what the Ingress
already does.

### 10.3 CORS

```bash
FRONTEND_ORIGIN=https://yourdomain.com
```
The gateway allow-lists exactly one origin. Leave it as `localhost:3000` and every browser
request fails CORS.

### 10.4 Frontend API URL — a build-time trap

`NEXT_PUBLIC_*` variables are **baked in at build time**, not read at runtime.

```bash
NEXT_PUBLIC_API_BASE_URL=https://yourdomain.com/api
```
Change it and you must **rebuild the image**. Setting it in the container env after the
build does nothing — a genuinely confusing failure.

Note it's resolved by the **browser**, so it must be a public URL, never a Docker/k8s
service name.

### 10.5 Kubernetes / Helm

```bash
helm upgrade --install careerlens k8s/helm/careerlens \
  --set global.imageRegistry=ghcr.io/harishvijayv/careerlens \
  --set global.imageTag=sha-<commit> \
  --set global.imagePullPolicy=Always \
  --set ingress.host=yourdomain.com \
  --set ingress.tls.enabled=true \
  --set postgres.enabled=false \
  --set redis.enabled=false
```

| Setting | Local | Hosted | Why |
|---|---|---|---|
| `imagePullPolicy` | `IfNotPresent` | `Always` | kind loads images locally; cloud must pull |
| `imageTag` | `latest` | `sha-<commit>` | traceable deploys and real rollbacks |
| `postgres/redis.enabled` | `true` | `false` | use managed services — see below |
| `ingress.tls.enabled` | `false` | `true` | real HTTPS |

### 10.6 HTTPS certificates

```bash
helm repo add jetstack https://charts.jetstack.io
helm install cert-manager jetstack/cert-manager -n cert-manager --create-namespace --set installCRDs=true
```
Then a `ClusterIssuer` for Let's Encrypt. Free, auto-renewing.

### 10.7 Managed database — and back it up

Stop self-hosting Postgres in production. Running your own means owning backups, failover,
upgrades and point-in-time recovery.

```bash
DATABASE_URL=postgresql+psycopg://user:pass@your-managed-host:5432/careerlens
REDIS_URL=redis://your-managed-redis:6379/0
```

⚠️ **If you do self-host it, set up backups first.** A StatefulSet with no backup is one
`kubectl delete pvc` away from total loss.

### 10.8 Secrets

Never `kubectl create secret` by hand in production, and remember a Kubernetes Secret is
base64-**encoded**, not encrypted. Use **Sealed Secrets** or **External Secrets Operator**,
and enable encryption at rest on the cluster.

### 10.9 Database migrations ← will break you

The app currently calls `Base.metadata.create_all()`, which creates **missing** tables but
cannot express a **change** to an existing one. The first time you alter a column on real
data, it silently does nothing.

**Add Alembic before you have data you care about.**

### 10.10 The pipeline in cloud

| Local | Cloud equivalent |
|---|---|
| Local files / HDFS | S3 / GCS / OCI Object Storage |
| Local Spark | EMR, Dataproc, Databricks — or keep on a VM |
| Docker Compose Airflow | MWAA, Cloud Composer, or self-hosted |
| Postgres | RDS / Cloud SQL |

Pipeline **logic** doesn't change — only where storage and compute physically run. That
portability is the whole point of how it was built.

### 10.11 Enable CI deploy

In `.github/workflows/ci.yml`, change `if: false` on the deploy job to
`if: github.ref == 'refs/heads/main'`, and add `KUBE_CONFIG` (base64 kubeconfig) as a repo
secret. It already does `helm rollback` on failure.

### 10.12 Hosting checklist

- [ ] Google redirect URI added (HTTPS) + `.env` updated
- [ ] `COOKIE_SECURE=true`, `COOKIE_DOMAIN` set
- [ ] `FRONTEND_ORIGIN` = real domain
- [ ] `NEXT_PUBLIC_API_BASE_URL` set **and image rebuilt**
- [ ] `imagePullPolicy=Always`, image tagged by SHA
- [ ] TLS via cert-manager
- [ ] Managed Postgres + Redis, **with backups**
- [ ] Secrets via Sealed/External Secrets
- [ ] Alembic migrations in place
- [ ] CI deploy enabled with `KUBE_CONFIG`
- [ ] Resource limits reviewed for real traffic
- [ ] Billing alert set ← genuinely important

---

## 11. Real bugs and what they taught

Full list in [docs/LESSONS.md](docs/LESSONS.md) — 16 real bugs. The best five:

1. **Gateway let anyone impersonate anyone.** It forwarded client-supplied `X-User-Id`.
   → *If a value is trusted downstream, the boundary producing it must destroy any client copy.*
2. **Only one of two auth cookies survived login.** `dict(headers)` collapsed duplicate
   `Set-Cookie`. → *HTTP headers are a multimap, not a map.*
3. **Pipeline worked once, broke on every re-run.** dbt views depended on tables being
   replaced. → ***A pipeline that hasn't been run twice hasn't been tested.***
4. **MCP publisher reported success while the topic stayed empty.** `send()` is async and
   nothing awaited the future. → *A publisher that lies about delivery is worse than none.*
5. **Frontend "Running" and "Ready" but serving nothing in k8s.** No `/health` route, so
   readiness failed forever and the Service had zero endpoints. → *`kubectl get endpoints`
   is the fastest way to tell a probe failure from an app bug.*

---

## 12. What's deliberately NOT here

Being able to say why something is absent is as valuable as building it.

| Missing | Why |
|---|---|
| LinkedIn/Indeed scraping | No free API; scraping violates their ToS. A portfolio project built on a ToS violation is a bad interview story |
| Alembic migrations | Known gap — §10.9. Needed before real data |
| Prometheus/Grafana | Known gap. "How would you know if this broke?" is the question it answers |
| Non-root containers | Images run as root; `runAsNonRoot: true` is a standard review item |
| NetworkPolicy | Done at the Docker layer for MCP; k8s equivalent not yet written |
| Load testing | HPA is configured but never proven. A `k6` run would turn config into evidence |
| Terraform | Clicking through a console isn't reproducible |
| MCP authentication | Fine on localhost; public hosting needs token auth first |

---

## 13. Interview answers

**"Walk me through this project."**
> A data pipeline processes job postings through Spark into a dbt star schema, six FastAPI
> microservices serve it behind an API gateway with JWT auth and Redis caching, and a
> multi-agent AI layer sits on top. It runs on Kubernetes with self-healing and a CI
> pipeline that publishes images to a registry. I benchmarked my Spark implementation
> against raw MapReduce — 57% faster — and I can explain exactly why.

**"Why Hadoop if Spark replaced it?"**
> To prove I understand *why* Spark won, with my own numbers. MapReduce writes intermediate
> results to disk between every stage; Spark keeps them in memory across a DAG. I
> implemented the same aggregation both ways and measured 2.33×.

**"Is 200,000 rows big data?"**
> No, and I wouldn't claim it. It's the volume that fits on a laptop while exercising
> genuinely distributed code paths. The same job runs unchanged on a cluster — only the
> master URL changes. I'd rather quote a number I measured.

**"How do you stop the AI hallucinating numbers?"**
> Structurally. Agents can only read curated data that passed dbt's tests, they can only
> call tools I gave them, and the UI shows every tool call so any answer is auditable.

**"What was your hardest bug?"**
> The gateway forwarded a client-supplied `X-User-Id` header that downstream services
> trusted as identity — anyone could read anyone's data by sending a header. Found it by
> testing my own security claim rather than assuming it. Same thing happened with the MCP
> server: I documented a privacy boundary, tested it, found Docker put everything on one
> network, and enforced it properly with network isolation.

**"How does it recover from failure?"**
> Four layers: the container restart policy, liveness probes for wedged-but-alive
> processes, Deployment replicas for lost pods or nodes, and `helm rollback` on a failed
> release. I verified the third by deleting a gateway pod mid-request — zero failed
> requests, replacement running in 40 seconds.

---

## Where to go next

| Doc | For |
|---|---|
| [SETUP_CHECKLIST.md](SETUP_CHECKLIST.md) | Getting it running |
| [docs/CREDENTIALS.md](docs/CREDENTIALS.md) | Every key |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design |
| [docs/DATA_ENGINEERING.md](docs/DATA_ENGINEERING.md) | Pipeline deep dive |
| [docs/AGENTIC_AI.md](docs/AGENTIC_AI.md) | Agent design |
| [docs/AUTH_AND_SECURITY.md](docs/AUTH_AND_SECURITY.md) | Auth deep dive |
| [docs/KUBERNETES.md](docs/KUBERNETES.md) | Running on k8s |
| [docs/CLOUD_LEARNING_PLAN.md](docs/CLOUD_LEARNING_PLAN.md) | Getting to cloud, free |
| [docs/LESSONS.md](docs/LESSONS.md) | 16 real bugs |

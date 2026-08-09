# CHEATSHEET — the whole project in 5 minutes

The short version. [HANDBOOK.md](HANDBOOK.md) is the long one; read that when you need
*why*. This is *what*.

---

## What it is

Upload your resume → it finds real jobs you can apply to, scores how well you match,
rewrites your resume for a role, tracks applications by reading your Gmail, and rings a
bell when a new posting matches your profile.

Underneath: a batch data pipeline, a modelled warehouse, an ML model, and six AI agents.

**200,866 job postings** — 4,907 live from Adzuna, the rest generated for volume.

---

## The pipeline, in order

```
Adzuna API + generator            1. two sources write plain JSON files
        ↓
   data/raw/*.jsonl               2. landing zone — never edited
        ↓
   PySpark ETL                    3. dedupe, fix salaries, extract skills
        ↓
   *.parquet                      4. columnar files, small + fast
        ↓
   Spark MLlib                    5. train + score every posting
        ↓
   COPY into Postgres             6. bulk load, not row-by-row
        ↓
   dbt run + dbt test             7. star schema + 17 tests. FAILS on bad data.
        ↓
   analytics.*                    8. the app reads only this
```

One command, ~7 minutes:
```bash
cd pipeline && python run_pipeline.py
```

---

## Every tech, one line each

### Data
| Tech | What it does here |
|---|---|
| **PySpark** | Splits the cleaning across all CPU cores. Dedupe, salary parsing, skill counts. |
| **Hadoop MapReduce** | Same job written the old way — to *measure* that Spark is 57.1% faster, not claim it. |
| **Spark MLlib** | Gradient-boosted trees. Predicts what a role should pay → the "vs market" badge. |
| **dbt** | SQL files that build the star schema **and test it**. Bad data fails the run. |
| **Parquet** | Column-based file format. Reading one column doesn't load the rest. |
| **PostgreSQL** | Where everything lives — your data + the warehouse. |
| **Redis** | Cache, rate limits, job queue. Nothing permanent. |
| **Airflow** | Schedules the pipeline daily with retries + run history. Running, **DAG paused** — see below. |
| **Kafka** | Announces "new jobs found". The match consumer turns those into bell notifications. Running; consumer is started by hand, not yet a service. |
| **Snowflake** | Cloud warehouse alternative. **The only paid thing.** Not configured — dbt falls back to Postgres. |

### Backend
| Tech | What it does here |
|---|---|
| **FastAPI** | All 5 services. Typed, async, auto-generates API docs. |
| **API Gateway** | The only public door. Checks your token once, forwards inward. |
| **JWT** | Signed token in an httpOnly cookie. No DB lookup per request. |
| **Refresh tokens** | Stored **hashed** in Postgres. Lets you revoke a session; a JWT alone can't. |
| **bcrypt** | Password hashing. Deliberately slow. |
| **Celery** | Runs slow jobs (Gmail sync) off the request path, via a Redis queue. |
| **SQLAlchemy** | ORM. Parameterised queries → SQL injection impossible by construction. |

### AI
| Tech | What it does here |
|---|---|
| **Fireworks (DeepSeek)** | The LLM. Swappable to OpenAI/Anthropic/Gemini by one config line. |
| **Tool-calling loop** | ~60 lines, written from scratch. *This is the agent.* |
| **LangGraph** | The same flow as a framework graph — for comparison. |
| **MCP server** | Exposes job data to *external* AI clients. Own network, can't reach auth. |

### Frontend
Next.js 16 · React 19 · TypeScript · Tailwind v4 · **inline SVG charts, no chart library**

### Infra
Docker · Docker Compose · Kubernetes · Helm · kind · Nginx · GitHub Actions → GHCR

---

## The containers

Nine by default. The `bigdata` profile adds Kafka, Airflow, HDFS and the Kafka UI (~1.2GB).

| Container | Job |
|---|---|
| **frontend** | The website (10 pages) |
| **gateway** | Only public door. Verifies JWT, strips forged headers. |
| **auth-service** | You: account, profile, resumes, applications, Google token |
| **jobs-service** | Job search + analytics. **Read-only.** |
| **agent-service** | The 6 AI agents |
| **worker-service** | Celery. Gmail sync. **No web port** — pulls from a queue. |
| **mcp-server** | External AI access. Isolated network. |
| **postgres** | Everything permanent |
| **redis** | Cache + queue |

**Page → service:** Jobs & Analytics → `jobs-service` · Resume, Applications, Profile → `auth-service` · Assistant → `agent-service`

---

## How the agents work

```
your question
   ↓
planner        picks ONE specialist, or escalates to the team
   ↓
agent loop:    model asks for a tool → OUR Python runs it → result goes back → repeat
   ↓
answer
```

The model can't *do* anything. It only asks. Our code validates and executes.

| Agent | Can call | Cannot |
|---|---|---|
| `job_matcher` | get_profile, search_jobs, get_job | write anything |
| `resume_tailor` | get_resume, get_job, save_tailored_resume | read email |
| `market_analyst` | get_market_analytics, search_jobs | see personal data |
| `skill_extractor` | *(no tools)* | — |
| `profile_extractor` | *(no tools)* | write the profile |
| `email_classifier` | *(no tools)* | **touch your resume** |

Limits: 6 tool calls per agent, 3 calls per single tool, 4 delegations.

---

## Where AI is — and isn't

| Feature | Actually powered by |
|---|---|
| Analytics charts | **SQL** |
| Job search + filters | **SQL** |
| "vs market" badge | **Spark MLlib** (trained ML, not an LLM) |
| Skill extraction in pipeline | **regex** |
| Gmail first-pass filter | **Gmail's own search** |
| Assistant, resume tailoring, email labelling | **LLM** |

---

## The numbers

| | |
|---|---|
| Postings | 200,866 (4,907 real) |
| Skill rows | 982,825 |
| Spark vs MapReduce | **57.1% faster (2.33×)** |
| ML model | GBT **R² 0.617** vs baseline 0.475 — *trained on real data only* |
| dbt tests | 17/17 passing |
| Python tests | 33 |
| Search speed | 2.0s → **0.52s** after adding indexes |

---

### Does it actually run on a schedule? Honestly: not yet

The DAG is **loaded but paused**, and has never run — `airflow dags list-runs` returns
"No data found". Right now the pipeline runs when you type `python run_pipeline.py`, and
at no other time.

Two things have to be true for a 2am run to happen, and both are easy to miss:

1. **The DAG must be unpaused.** New DAGs start paused on purpose, so switching Airflow on
   never launches something unexpected.
   ```bash
   docker compose exec airflow-scheduler airflow dags unpause job_pipeline
   ```
2. **The machine must be awake.** Airflow is a container on your laptop. Shut the laptop
   and the scheduler stops with it — and `catchup=False` means it does **not** run the
   missed days when you come back. A missed day is simply missed.

That second point is the real argument for hosting it: on a server that never sleeps, the
schedule genuinely holds. On a laptop, "daily at 2am" means "daily at 2am **on days the
laptop happens to be on at 2am**", which is not a schedule.

**The run history** lives at http://localhost:8080 (Airflow UI). Once it has run a few
times you get a grid of every run, green or red per task, with the logs of any failure
and a button to re-run just the failed step. That history is the thing you cannot get
from typing a command yourself — it is the reason Airflow exists.

## Commands

```bash
# run everything
cd infra && docker compose up -d

# stop
docker compose stop

# refresh job data (~7 min)
cd pipeline && python run_pipeline.py

# just new postings
python run_pipeline.py --only real,spark,load,dbt

# turn on Airflow + Kafka   (Airflow :8080 · Kafka UI :8085 · Adminer :8081)
docker compose --profile bigdata up -d

# make the daily schedule actually happen (it starts paused)
docker compose exec airflow-scheduler airflow dags unpause job_pipeline

# free 3GB — the Kubernetes practice cluster is NOT the app
kind delete cluster --name careerlens

# after changing code
docker compose up -d --build

# if a change doesn't appear
docker compose up -d --build --force-recreate --renew-anon-volumes
```

---

## Say this in an interview

**On scale, before they ask:**
> "4,907 postings are real; the rest are generated so the distributed path runs at a size
> where Spark is the right tool. 5,000 rows wouldn't justify it — pandas would do."

**On the ML model:**
> "It scored 0.898 trained on everything, but 96% of that was seniority because that's how
> my generator computes salary — it had learned the generator, not the market. Retrained on
> real postings it's 0.617, region became the top feature, and it beats the linear baseline
> by 4× the margin. I'd rather quote the number I can defend."

**On data quality:**
> "dbt runs 17 tests and fails the pipeline if any fail, so bad data never reaches the app."

**The best bug:**
> "My salary cleaner stripped non-digits, turning 160000.0 into 1600000. Invisible for
> months because my generator only emitted whole numbers — the first real API value made
> average US salary read $10 million. A transformation that's correct for all *current*
> inputs isn't the same as a correct transformation."

**On agents:**
> "The model never executes anything. It requests a tool by name, my code checks it's
> allowed and runs it. The email agent physically cannot touch a resume — it was never
> given that tool."

---

## Over-engineered? Yes, on purpose — and say so first

At 152k rows a laptop and a few scripts would do. Three tools are demonstrations of a
pattern, not solutions to a problem this project actually had:

| Tool | Needed here? | What would do instead | Becomes necessary when |
|---|---|---|---|
| **Spark** | no (85MB fits in RAM) | pandas | data outgrows one machine |
| **Airflow** | no | `cron` + a shell script | you need task retries, backfills, and run history |
| **Kafka** | no | a direct function call | several consumers react to one event independently |
| **Snowflake** | no | Postgres | analytical scans outgrow one server |
| **Kubernetes** | no | Docker Compose | rolling deploys, self-healing, scaling |

**These four ARE load-bearing at any size** — keep them even in a tiny project:
dbt's tests · the star schema · Parquet · Redis caching

**Why Airflow beats cron once it matters:** cron reruns the whole 7-minute pipeline; Airflow
retries the one step that failed. Cron runs on a clock; Airflow runs `dbt test` *because*
`dbt run` succeeded. And cron can't answer "it failed twice last month, here are the logs".

**Why Kafka beats a direct call once it matters:** if consumer B is broken, a direct call
takes the producer down with it. A broker doesn't. That independence is the whole purchase
— and it's worth nothing until there's more than one consumer.

**Say this:**
> "Spark, Kafka and Airflow aren't load-bearing at 152,000 rows — pandas and a cron job
> would do it. I built them so the decisions were real: why cache, why a native expression
> over a UDF, why fan-out needs a broker. What IS load-bearing at any size is dbt's tests,
> the star schema and Redis caching."

Better than claiming you needed a cluster. It shows you can size a solution to a problem.

---

## What is automated

All of it, as long as Docker is running:

| | Automatic? | How |
|---|---|---|
| Fetching new jobs | **yes** | Airflow DAG, `@daily`, unpaused |
| Spark ETL + model training | **yes** | tasks 3 and 4 of the same DAG |
| Warehouse load + dbt tests | **yes** | tasks 5-7; a failed test stops the run |
| Kafka events | **yes** | published by the ingest task |
| Bell notifications | **yes** | `match-notifier` container, `restart: unless-stopped` |

```bash
docker compose --profile bigdata up -d      # that is the whole setup
```

Verified: a full DAG run with all 7 tasks green — real Adzuna fetch (5 min), Spark,
MLlib, load, dbt run, dbt test.

**The one honest caveat:** Airflow is a container on your laptop, so it only runs while
Docker is up, and `catchup=False` means a missed day is missed rather than queued. On a
server that never sleeps the schedule genuinely holds — which is a better argument for
hosting this than the public URL.

- Airflow UI: **http://localhost:8080** — run history, per-task logs, retry a single step
- Kafka UI: **http://localhost:8085** — topics and message contents

---

## Known gaps — say these before they're found

- **No incremental loading** — full refresh every run
- **Airflow written but not running**
- **Never actually distributed** — single-node Spark
- **Kafka wired but idle**
- **No monitoring/alerting**
- Skills found on only ~19% of real postings (Adzuna truncates descriptions)
- Only ~24% of Indian postings publish a salary

---

**More detail:** [HANDBOOK.md](HANDBOOK.md) · **Deploying:** [DEPLOYMENT.md](DEPLOYMENT.md)

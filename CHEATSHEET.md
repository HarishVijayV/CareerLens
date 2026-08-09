# CHEATSHEET — the whole project as a flow

Every box below is a real thing in the repo. For each one: **what goes in, what comes out,
and why it exists.** Follow the arrows top to bottom.

[HANDBOOK.md](HANDBOOK.md) is the long version — read that when you need *why* a decision
was made. This is *what happens, in order*.

---

## The map

```
                        ┌──────────────────────────────────────────┐
                        │  A. TWO SOURCES                          │
                        │  Adzuna API        synthetic generator   │
                        └───────┬──────────────────────┬───────────┘
                                │  4,907 real          │  ~196k fake
                                └──────────┬───────────┘
                                           ▼
                                ┌────────────────────┐
                                │  B. RAW LANDING    │   *.jsonl on disk
                                │  never edited      │   205,000 rows
                                └─────────┬──────────┘
                                          ▼
                                ┌────────────────────┐
                                │  C. PySpark ETL    │   clean · dedupe · skills
                                └─────────┬──────────┘
                                          ▼
                                ┌────────────────────┐
                                │  D. PARQUET        │   columnar, on disk
                                └─────────┬──────────┘
                                          │
                    ┌─────────────────────┴─────────────────────┐
                    ▼                                           ▼
        ┌────────────────────┐                      ┌────────────────────┐
        │  E. Spark MLlib    │                      │  F. COPY loader    │
        │  train + score     │                      │  bulk insert       │
        └─────────┬──────────┘                      └─────────┬──────────┘
                  │  predicted salary per posting             │
                  └─────────────────┬─────────────────────────┘
                                    ▼
                          ┌────────────────────┐
                          │  G. Postgres raw.* │
                          └─────────┬──────────┘
                                    ▼
                          ┌────────────────────┐
                          │  H. dbt run        │   star schema
                          │  H2. dbt test      │   17 tests — FAILS the run
                          └─────────┬──────────┘
                                    ▼
                          ┌────────────────────┐
                          │  I. analytics.*    │  ◄── the ONLY thing the app reads
                          └─────────┬──────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        ▼                           ▼                           ▼
┌───────────────┐        ┌───────────────────┐       ┌────────────────────┐
│ J. jobs-svc   │        │ K. agent-service  │       │ L. Kafka events    │
│ search+charts │        │ 6 AI agents       │       │ posting.discovered │
└───────┬───────┘        └─────────┬─────────┘       └─────────┬──────────┘
        │                          │                           ▼
        │                          │                 ┌────────────────────┐
        │                          │                 │ M. match-notifier  │
        │                          │                 │ per-profile match  │
        │                          │                 └─────────┬──────────┘
        │                          │                           ▼
        │                          │                 ┌────────────────────┐
        │                          │                 │ N. notifications   │
        │                          │                 │ table              │
        └──────────┬───────────────┴───────────────────────────┘
                   ▼
        ┌────────────────────────────────┐
        │  O. GATEWAY  (JWT · CORS · rate limit)
        └───────────────┬────────────────┘
                        ▼
        ┌────────────────────────────────┐
        │  P. Next.js — 10 pages + bell  │
        └────────────────────────────────┘

   Above it all:  Q. AIRFLOW  triggers A→H2 every day at midnight
```

---

## Every node explained

### A — Two sources

| | |
|---|---|
| **In** | your profile's target roles + countries |
| **Out** | `real_postings.jsonl` (4,907) · `synthetic_postings.jsonl` (~196k) |
| **Code** | `pipeline/ingestion/job_apis.py` · `generate_synthetic_data.py` |

Adzuna is queried per search term, per country, 5 pages each. Terms come from **your
profile**, not a hardcoded list, so the warehouse fills with roles you would actually apply
to.

Four things are fixed here, at the edge, so nothing downstream needs per-source branching:
salary converted to **USD** (Adzuna returns each country's currency as a bare number),
**skills extracted** by regex from the description (Adzuna has no tags field), **seniority
inferred** from the title, and salaries below $5,000/yr **nulled** — those are monthly
Indian figures in an annual field, and a guessed salary is worse than a missing one.

**Why synthetic too:** 4,907 real rows do not justify Spark. The generated rows exist so
the distributed path runs at a size where its optimisations are measurable.

---

### B — Raw landing zone

| | |
|---|---|
| **In** | whatever the sources wrote |
| **Out** | the same bytes, unchanged |
| **Code** | `pipeline/data/raw/*.jsonl` |

Nothing edits this. If a bug is found in the ETL you reprocess from here instead of
re-downloading — which matters because Adzuna's free tier is a daily quota.

---

### C — PySpark ETL

| | |
|---|---|
| **In** | `data/raw/*.jsonl` — **both** files, one glob |
| **Out** | cleaned rows + 4 aggregate tables |
| **Code** | `pipeline/spark_jobs/etl_clean_jobs.py` |

One glob means **one cleaning path**, not one per source. It dedupes on `posting_id`,
parses salaries, trims titles, and materialises `skill_count`.

Three decisions worth being able to defend:

- **`cache()`** — Spark is lazy and recomputes the whole chain each time you ask for a
  result. `cleaned` is used 6 times, so without this the read-and-clean runs 6 times.
- **Native SQL, not a Python UDF** — a UDF ships every row out of the JVM into Python and
  back. Native expressions stay in the JVM.
- **`skill_count` computed once** — the ML model and the analytics both want it.

---

### D — Parquet

| | |
|---|---|
| **In** | cleaned rows |
| **Out** | `data/curated/postings.parquet` |

Stored by **column**, not row. Reading only `salary` never touches the other fields, and
repeated values compress hard. Same data, a fraction of the size and read time.

---

### E — Spark MLlib

| | |
|---|---|
| **In** | curated Parquet, **real postings only** |
| **Out** | `predicted_salary`, `salary_vs_market`, `pay_band` for **every** posting |
| **Code** | `pipeline/spark_jobs/mllib_salary_model.py` |

Gradient-boosted trees. Four features → salary. Trained fresh each run, not downloaded.

**Trained on real rows only, and that is the point.** On everything it scored R²=0.898 —
but 96% of that was seniority, because that is how the generator computes salary. It had
learned the generator, not the market. On real postings R² drops to **0.617**, region
becomes the top feature (a US role genuinely pays multiples of an Indian one), and GBT
beats the linear baseline by 4× the margin. *Prefer the number you can defend.*

Scoring still covers every posting — `--real-only` narrows what it **learns from**, never
what it is **applied to**.

---

### F — COPY loader

| | |
|---|---|
| **In** | curated Parquet |
| **Out** | rows in Postgres `raw.*` |
| **Code** | `pipeline/ingestion/load_to_warehouse.py` |

`COPY`, not row-by-row `INSERT`. INSERT sends 200,000 separate statements; COPY streams
the file once. Minutes versus seconds.

---

### G — Postgres `raw.*`

Landing tables, exactly as loaded. Nothing queries these except dbt.

---

### H — dbt run → H2 — dbt test

| | |
|---|---|
| **In** | `raw.*` |
| **Out** | `analytics.*` star schema |
| **Code** | `pipeline/dbt/` — 5 models, 17 tests |

Reshapes flat rows into:

```
              dim_company
                   │
  dim_skill ── bridge_posting_skill ── fact_job_posting
```

**Why a bridge table, not an array column:** array handling differs per engine (Postgres
`unnest` vs Snowflake `FLATTEN`). Bridge rows are plain SQL that works identically
everywhere.

**H2 is the quality gate.** 17 tests — no nulls in keys, no duplicate ids, salary in range.
`dbt test` **fails the pipeline** if any fail, so bad data never reaches the app. That is
a far better answer to "how do you ensure data quality" than "we check manually".

Indexes are attached here as **post-hooks**, because dbt drops and recreates each table
every run — an index made by hand survives until the next run and then silently vanishes.
Adding them took search from **2.0s → 0.52s**.

---

### I — `analytics.*`

The only thing the app is allowed to read. Everything here has passed the tests.

**This is the answer to "how do you stop an LLM hallucinating numbers":** you don't let it
near unvalidated data in the first place.

---

### J — jobs-service

| | |
|---|---|
| **In** | HTTP search/filter params |
| **Out** | JSON job rows + analytics |

Read-only, so it caches hard in Redis. Ordering is **real postings first**, then your
region, then how many of your skills the role wants, then salary.

---

### K — agent-service

| | |
|---|---|
| **In** | your question |
| **Out** | an answer + every tool call it made |

```
question → planner ─┬─ "none"        → direct reply, no tools
                    ├─ one specialist → that agent answers
                    └─ "orchestrator" → several agents, combined answer
```

The agent loop: **model asks for a tool → our Python validates and runs it → result goes
back → repeat.** The model executes nothing itself.

| Agent | Tools | Cannot |
|---|---|---|
| `job_matcher` | get_profile, search_jobs, get_job | write anything |
| `resume_tailor` | get_resume, get_job, save_tailored_resume | read email |
| `market_analyst` | get_market_analytics, search_jobs | see personal data |
| `skill_extractor` | none | — |
| `profile_extractor` | none | write the profile |
| `email_classifier` | none | **touch your resume** |

Limits: 6 tool calls per agent, 3 per single tool, 4 delegations.

---

### L → M → N — Kafka, consumer, notifications

| | In | Out |
|---|---|---|
| **L** Kafka | one `posting.discovered` per new job | held in a topic |
| **M** match-notifier | every event + every profile | a match, or nothing |
| **N** notifications table | matches | rows the bell reads |

**Kafka carries, it decides nothing.** The consumer holds the logic: *2+ of your skills
overlap, OR your target role is in the title.* Two accounts on identical events get
different notifications.

**Why a broker at all:** several consumers read the same event independently, and one
breaking must not stop the others. With direct calls, a broken notifier takes ingestion
down with it.

**In-app, not email:** the consumer fires per posting, so 200 new jobs would send 200
emails. A badge showing "12" is the same information without the spam.

Duplicates are stopped by a **unique constraint** on (user_id, posting_id) — a consumer
restarts and forgets, a constraint does not.

---

### O — Gateway

| | |
|---|---|
| **In** | every browser request |
| **Out** | forwarded to one service, or 401 |

The only public door. Four middleware, in order: **CORS → logging → auth → rate limit.**

It verifies your JWT once so no other service needs auth code, and **deletes any
`X-User-Id` the client sent** before adding its own — without that, anyone could read your
profile by typing a header.

---

### P — Frontend

10 Next.js pages. Charts are **inline SVG, no chart library**. The bell polls an endpoint
that returns a single integer every 60 seconds.

---

### Q — Airflow

| | |
|---|---|
| **In** | the clock |
| **Out** | runs A → H2, daily |

Seven tasks, `@daily`, unpaused. What it adds over typing the command: **task-level
retries** (retries the failed step, not all 7 minutes), **dependencies** (`dbt test` runs
because `dbt run` succeeded), and **history** — "ran 47 times, failed twice, here are the
logs" is a question a shell script cannot answer.

Caveat worth saying first: it is a container on a laptop, so it runs while Docker runs,
and `catchup=False` means a missed day is missed rather than queued.

---

## What is automated

All of it, while Docker is up:

```bash
docker compose --profile bigdata up -d      # the whole setup
```

Verified: a full DAG run, all 7 tasks green, including a real 5-minute Adzuna fetch.

- Airflow UI **http://localhost:8080** — run history, per-task logs, retry one step
- Kafka UI **http://localhost:8085** — topics and message contents

---

## Where AI is — and isn't

| Feature | Actually |
|---|---|
| Analytics charts | **SQL** |
| Job search + filters | **SQL** |
| "vs market" badge | **Spark MLlib** — trained ML, not an LLM |
| Skill extraction in the pipeline | **regex** |
| Gmail first-pass filter | **Gmail's own search** |
| Assistant · resume tailoring · email labelling | **LLM** |

---

## The numbers

| | |
|---|---|
| Postings | 200,866 (4,907 real) |
| Skill rows | 982,825 |
| Spark vs MapReduce | **57.1% faster (2.33×)** |
| ML model | GBT **R² 0.617** vs baseline 0.475 — real data only |
| dbt tests | 17/17 |
| Python tests | 33 |
| Job search | 2.0s → **0.52s** after indexing |

---

## Over-engineered? Yes, deliberately — say so first

At 200k rows a laptop and a few scripts would do. Three tools are demonstrations:

| Tool | Needed here? | Instead | Becomes necessary when |
|---|---|---|---|
| **Spark** | no (~100MB) | pandas | data outgrows one machine |
| **Airflow** | no | `cron` | you need task retries + run history |
| **Kafka** | no | a direct call | a 2nd independent consumer appears |
| **Snowflake** | no | Postgres | scans outgrow one server |
| **Kubernetes** | no | Docker Compose | rolling deploys, self-healing |

**Load-bearing at any size:** dbt's tests · the star schema · Parquet · Redis caching.

> "Spark, Kafka and Airflow aren't load-bearing at 200,000 rows — pandas and a cron job
> would do it. I built them so the decisions were real: why cache, why a native expression
> over a UDF, why fan-out needs a broker. What IS load-bearing at any size is dbt's tests,
> the star schema and Redis caching."

---

## Best interview answers

**The bug worth telling:**
> "My salary cleaner stripped non-digits, turning 160000.0 into 1600000. Invisible for
> months because my generator only emitted whole numbers — the first real API value made
> average US salary read $10 million. A transformation correct for all *current* inputs
> isn't the same as a correct transformation."

**On the model:**
> "0.898 trained on everything, but 96% of that was seniority because that's how my
> generator computes salary — it had learned the generator, not the market. Retrained on
> real postings it's 0.617 and region became the top feature. I'd rather quote the number
> I can defend."

**On agents:**
> "The model never executes anything. It requests a tool by name, my code checks it's
> allowed and runs it. The email agent physically cannot touch a resume — it was never
> given that tool."

---

## Known gaps — say these before they're found

- **No incremental loading** — full refresh every run
- **Never actually distributed** — single-node Spark
- **No monitoring/alerting** on the pipeline
- Skills found on only ~20% of real postings (Adzuna truncates descriptions)
- Only ~24% of Indian postings publish a salary
- Airflow only runs while your laptop does

---

**More detail:** [HANDBOOK.md](HANDBOOK.md) · **Deploying:** [DEPLOYMENT.md](DEPLOYMENT.md)

# CHEATSHEET — the whole project in 5 minutes

The short version. [HANDBOOK.md](HANDBOOK.md) is the long one; read that when you need
*why*. This is *what*.

---

## What it is

Upload your resume → it finds real jobs you can apply to, scores how well you match,
rewrites your resume for a role, and tracks applications by reading your Gmail.

Underneath: a batch data pipeline, a modelled warehouse, an ML model, and six AI agents.

**151,883 job postings** — 4,911 live from Adzuna, the rest generated for volume.

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
| **Airflow** | Runs the pipeline daily with retries. Written, **switched off** (RAM). |
| **Kafka** | Announces "new jobs found" so services can react. Written, **switched off** (RAM). |
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

## The 9 containers

| Container | Job |
|---|---|
| **frontend** | The website (7 pages) |
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
| Postings | 151,883 (4,911 real) |
| Skill rows | 737,525 |
| Spark vs MapReduce | **57.1% faster (2.33×)** |
| ML model | GBT **R² 0.617** vs baseline 0.475 — *trained on real data only* |
| dbt tests | 17/17 passing |
| Python tests | 33 |
| Search speed | 2.0s → **0.52s** after adding indexes |

---

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

# turn on Airflow + Kafka
docker compose --profile bigdata up -d

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
> "4,911 postings are real; the rest are generated so the distributed path runs at a size
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

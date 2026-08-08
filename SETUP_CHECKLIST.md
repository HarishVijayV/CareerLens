# Your Setup Checklist

Everything that can be automated already is. This is the short list of things only you
can do, in order. **Total time: about 15 minutes**, and only step 1 is strictly required.

---

## Step 1 — Get an LLM API key (5 min) — REQUIRED for the AI Copilot

Without this, everything works except the AI agents.

**Use Google Gemini.** It's the only provider with a genuinely *permanent* free tier —
the others give trial credits and then charge. This matters because you said you need it
to keep working for years without paying.

1. Go to **https://aistudio.google.com/apikey**
2. Sign in with your Google account → **Create API key**
3. Copy the key
4. Open `infra/.env` and set:
   ```
   LLM_PROVIDER=gemini
   GEMINI_API_KEY=<paste your key here>
   ```
5. Restart the agent service:
   ```bash
   cd infra && docker compose restart agent-service
   ```

> No credit card required. Free tier is rate-limited (plenty for personal use).
> To switch providers later, change `LLM_PROVIDER` to `fireworks`, `openai`, or
> `anthropic` and set that provider's key — no code changes, that's what the provider
> abstraction is for.

---

## Step 2 — Get Adzuna job API keys (5 min) — OPTIONAL but recommended

This is the source that covers **both India and USA**, so it's the one that keeps
mattering when you move to the US for your MS.

1. Go to **https://developer.adzuna.com/**
2. Sign up (free, no card) → you get an **App ID** and an **App Key**
3. Put them in `infra/.env`:
   ```
   ADZUNA_APP_ID=<your app id>
   ADZUNA_APP_KEY=<your app key>
   ```

Without these, ingestion still works — it just uses Remotive only (remote jobs, no key
needed).

---

## Step 3 — Look at it (2 min)

Everything below is already running on your machine right now.

```bash
# if the containers aren't up:
cd infra && docker compose up -d

# the frontend:
cd frontend && npm run dev
```

Then open **http://localhost:3000**, sign up with any email/password (min 8 chars), and
click through: Dashboard → Jobs → Analytics → Copilot → Profile.

A test account already exists if you prefer: `harish@example.com` / `testpass1234`

---

## Step 4 — Re-run the pipeline whenever you want fresh data

One command does everything (generate → fetch real jobs → Spark ETL → train model →
load warehouse → dbt build + test):

```bash
cd pipeline
python run_pipeline.py                  # ~3 min, 200k rows
python run_pipeline.py --rows 1000000   # scale it up
python run_pipeline.py --benchmark      # include the MapReduce vs Spark comparison
```

---

## Step 5 — Upload your resume (1 min, no credentials needed)

Open **http://localhost:3000/resume** and upload your resume.

**Upload the `.tex` file if you have it.** That's the format where the whole loop works:

    upload .tex -> ask the assistant to rewrite it -> download a compiled .pdf

PDF upload works too, but it's one-way: text can be pulled out of a PDF, but there's no
route back to a formatted PDF from that text. `.docx` and `.txt` also work.

No Google account, no API key, no OAuth — resume upload talks only to your own backend.

What you can do there:
- Edit in the browser (plain-text tab, or the LaTeX tab if you uploaded .tex)
- Chat with the resume assistant: "convert my resume to LaTeX", "rewrite my bullets to
  emphasise data engineering", "tailor this for posting P000177873"
- Download `.txt`, `.tex`, or a real compiled `.pdf`
- Restore any previous version — every save is kept, nothing is overwritten

*(The chat needs your LLM key from Step 1. Upload, edit and download work without it.)*

---

## Step 6 — LATER (not now): Gmail integration

Only needed for the email-tracking feature, which is Phase 6 in `docs/ROADMAP.md` and not
built yet. When you get there: Google Cloud Console → create OAuth credentials → enable
Gmail API (readonly scope). **Free**, and staying in "Testing" mode with yourself as a
test user keeps it free forever.

---

## What's already done for you

You don't need to touch any of this — it's installed, configured, and verified working:

- Java 17 (installed to `~/.jre`) and `winutils.exe` (`~/hadoop`) so Spark runs on Windows
- Docker services: Postgres, Redis, Kafka, gateway, auth, agent, jobs, notification
- `infra/.env` created with a strong random JWT secret already generated
- 195,959 job postings processed and loaded into the warehouse
- dbt star schema built, all 17 data-quality tests passing
- 24 Python tests passing

## Verified results already measured on your machine

| What | Result |
|---|---|
| Rows processed | 200,000 → 195,959 after dedup (4,041 duplicates removed) |
| Spark vs MapReduce | **Spark 57.1% faster (2.33×)** — median of 3 runs each |
| MLlib salary model | GBT **R² = 0.911** vs LinearRegression baseline R² = 0.178 |
| Warehouse | 195,959 postings + 980,447 skill rows |
| dbt | 5 models, **17/17 tests pass** |
| Airflow DAG | 7 tasks, parses with 0 import errors |

These are *your* numbers, measured — use them on your resume instead of the old inherited
"40%" claim. Full JSON in `pipeline/data/benchmark_results.json` and
`pipeline/data/model_metrics.json`.

---

## If something breaks

| Symptom | Fix |
|---|---|
| Copilot returns a 502 | LLM key missing/invalid — see Step 1, then `docker compose restart agent-service` |
| Analytics page empty | Pipeline hasn't run — `cd pipeline && python run_pipeline.py` |
| `docker compose` port conflict | Change the port in `infra/.env` |
| Spark: "Python was not found" | Handled automatically in `pipeline/spark_jobs/spark_common.py` |
| Spark: `HADOOP_HOME unset` | winutils already installed at `~/hadoop`; auto-detected |
| `FileNotFoundError` on a file that exists | Windows 260-char path limit — see `pipeline/paths.py` |
| Services won't start | `cd infra && docker compose logs <service-name>` |

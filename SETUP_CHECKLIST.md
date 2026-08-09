# Your Setup Checklist

Everything that can be automated already is. This is the short list of things only you
can do, in order. **Total time: about 15 minutes**, and only step 1 is strictly required.

---

## Step 1 — Get an LLM API key (5 min) — REQUIRED for the AI Copilot

Without this, everything works except the AI agents.

**Use Fireworks** — you already have credits there, and it's the right choice for this
workload. Agents make **3-6 LLM calls per question** (plan -> call tool -> read result ->
answer), and the inbox sync makes one call *per email*. Gemini's permanent free tier is
capped per MINUTE, which stalls an agent mid-loop rather than failing cleanly.

1. Go to **https://app.fireworks.ai/settings/users/api-keys**
2. Create a key and copy it
3. Open `infra/.env` and set:
   ```
   LLM_PROVIDER=fireworks
   FIREWORKS_API_KEY=<paste your key here>
   ```
4. Restart the agent service:
   ```bash
   cd infra && docker compose restart agent-service
   ```

> **When your Fireworks credits run out**, get a free permanent key at
> https://aistudio.google.com/apikey, set `GEMINI_API_KEY` and flip
> `LLM_PROVIDER=gemini`. One line, no code change — that's what the provider abstraction
> is for, and it's a good thing to be able to say in an interview.
>
> If agents answer without ever calling a tool, that's the MODEL, not the code — not every
> open model does tool-calling reliably. Try a different `FIREWORKS_MODEL`.

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
cd infra && docker compose up -d
```

**That's the only command.** It brings up everything — database, cache, Kafka, all six
backend services, and the frontend. Every container is set to `restart: unless-stopped`,
so once Docker Desktop starts, the whole stack comes back on its own and you don't need
to run anything at all.

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
- **PDF preview tab** — see the compiled document rendered in the page, next to the editor
- Download `.txt`, `.tex`, or a real compiled `.pdf`
- Restore any previous version — every save is kept, nothing is overwritten

*(The chat needs your LLM key from Step 1. Upload, edit and download work without it.)*

---

## Step 6 — OPTIONAL: Gmail application tracking

The feature is **fully built** — it just needs Google OAuth credentials, which are
**free forever** while your app stays in "Testing" mode.

1. https://console.cloud.google.com/ → create a project
2. **APIs & Services → Library** → enable **Gmail API**
3. **OAuth consent screen** → External → add your own email under **Test users**
4. **Credentials → Create Credentials → OAuth client ID → Web application**
5. Authorized redirect URI: `http://localhost:8000/api/auth/google/callback`
6. Put the Client ID + Secret in `infra/.env`, then:
   `cd infra && docker compose restart auth-service worker-service`

Then open `/applications` → **Connect Gmail** → **Sync inbox**. An agent reads your
inbox (read-only), classifies each message, and builds your applied → interview → offer
funnel automatically.

Full walkthrough: [docs/CREDENTIALS.md](docs/CREDENTIALS.md).

---

## What's already done for you

You don't need to touch any of this — it's installed, configured, and verified working:

- Java 17 (installed to `~/.jre`) and `winutils.exe` (`~/hadoop`) so Spark runs on Windows
- Docker services: Postgres, Redis, Kafka, gateway, auth, agent, jobs, notification
- `infra/.env` created with a strong random JWT secret already generated
- 200,868 job postings processed and loaded into the warehouse (4,909 of them live Adzuna listings)
- dbt star schema built, all 17 data-quality tests passing
- 33 Python tests passing
- LaTeX engine installed in the auth-service image, so resume PDF export works

## Verified results already measured on your machine

| What | Result |
|---|---|
| Rows processed | 204,909 → 200,868 after dedup (4,041 duplicates removed) |
| Spark vs MapReduce | **Spark 57.1% faster (2.33×)** — median of 3 runs each |
| MLlib salary model | trained on REAL postings only: GBT **R² = 0.617** vs baseline **0.475** |
| Warehouse | 200,868 postings + 982,853 skill rows |
| dbt | 5 models, **17/17 tests pass** |
| Airflow DAG | 7 tasks, parses with 0 import errors |
| Tests | 33 passing |
| Resume PDF export | verified — real compiled PDF from LaTeX |

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

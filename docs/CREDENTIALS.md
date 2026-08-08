# Every Credential — What It's For, What Breaks Without It

The complete list. Nothing here is hidden or assumed; every key states what degrades if
it's missing, and every one has a defined fallback.

**Design rule this follows:** no credential is ever *required* for the system to boot.
Missing keys degrade one feature and say so clearly — they never produce a mystery crash.

---

## Summary table

| Credential | Cost | Required? | Without it |
|---|---|---|---|
| `GEMINI_API_KEY` | **Free forever** | For AI features | Copilot returns a clear 502; everything else works |
| `ADZUNA_APP_ID` / `_KEY` | **Free** | No | Only Remotive is fetched (remote jobs, no India/USA coverage) |
| `GOOGLE_CLIENT_ID` / `_SECRET` | **Free** | No | Applications page shows "Gmail not configured"; manual entry still works |
| `TOKEN_ENCRYPTION_KEY` | — | No | Falls back to `JWT_SECRET_KEY` (fine for dev) |
| `JWT_SECRET_KEY` | — | **Yes** | Already generated for you |
| Snowflake (5 vars) | Free 30-day trial | No | **Automatically falls back to Postgres** — same dbt models |
| Postgres / Redis / Kafka | — | No | Already running in Docker, no signup |

---

## 1. LLM provider — pick ONE

Set `LLM_PROVIDER` and the matching key. The provider abstraction means switching is a
config change, never a code change.

| Provider | Free tier | Get a key |
|---|---|---|
| **`gemini`** ← default | **Permanent free tier**, rate-limited, no card | https://aistudio.google.com/apikey |
| `fireworks` | Trial credits, then paid | https://fireworks.ai |
| `openai` | Trial credits, then paid | https://platform.openai.com/api-keys |
| `anthropic` | Trial credits, then paid | https://console.anthropic.com |

```bash
LLM_PROVIDER=gemini
GEMINI_API_KEY=...
```

**Gemini is the default specifically because you need this to keep working for years
without paying.** The others expire into a bill.

**Without it:** the Copilot page returns a 502 that names the problem. Jobs, analytics,
auth, and the whole pipeline are unaffected.

---

## 2. Adzuna — job postings for India + USA

```bash
ADZUNA_APP_ID=...
ADZUNA_APP_KEY=...
```

Free, no card: https://developer.adzuna.com/ → sign up → get App ID + App Key.

**This is the one that covers both India (`in`) and USA (`us`)** from a single key, which
is why it matters for you specifically — same source before and after your MS.

**Without it:** ingestion still runs, but only Remotive (remote-only roles, no
country targeting). You'll see `adzuna: SKIPPED` in the pipeline output — deliberately
loud, not silent.

---

## 3. Google OAuth — Gmail application tracking

```bash
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=http://localhost:8000/api/auth/google/callback
```

**Completely free, permanently**, as long as the app stays in "Testing" mode with you as
a test user. No verification process, no billing.

Setup:
1. https://console.cloud.google.com/ → create a project
2. **APIs & Services → Library** → enable **Gmail API**
3. **OAuth consent screen** → External → add yourself under **Test users**
4. **Credentials → Create Credentials → OAuth client ID → Web application**
5. Authorized redirect URI: `http://localhost:8000/api/auth/google/callback`
6. Copy the Client ID and Client Secret into `infra/.env`
7. `cd infra && docker compose restart auth-service worker-service`

Scopes requested (read-only, nothing else): `gmail.readonly`, `userinfo.email`.

**Without it:** the Applications page says "Gmail not configured" and the Connect button
is hidden. Manual application entry, the funnel, and resume A/B all still work.

---

## 4. Token encryption key

```bash
TOKEN_ENCRYPTION_KEY=<any long random string>
```

Encrypts Google refresh tokens at rest. Generate one with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

**Without it:** falls back to `JWT_SECRET_KEY`. That works, but it couples two unrelated
secrets — rotating your JWT secret would orphan every stored Google token. Fine for local
dev, worth separating before anything real.

---

## 5. Snowflake — optional warehouse, automatic fallback

```bash
SNOWFLAKE_ACCOUNT=...
SNOWFLAKE_USER=...
SNOWFLAKE_PASSWORD=...
SNOWFLAKE_DATABASE=CAREERLENS
SNOWFLAKE_WAREHOUSE=COMPUTE_WH
```

Free 30-day trial (no card): https://signup.snowflake.com/

**The fallback is automatic and by design.** `pipeline/dbt/profiles.yml` defines two
targets — `dev` (Postgres) and `warehouse` (Snowflake) — running the *same models and the
same tests*. `run_pipeline.py` detects whether Snowflake credentials are present and picks
the target accordingly.

```bash
python run_pipeline.py                    # auto: Snowflake if configured, else Postgres
python run_pipeline.py --target dev       # force Postgres
python run_pipeline.py --target warehouse # force Snowflake
```

**Why it's worth doing before an interview:** run it once against Snowflake so you can say
"the same dbt models run against Postgres and Snowflake; only the target changes." Then
let the trial lapse — Postgres carries on.

**Without it:** everything works on Postgres. No feature is lost; you just don't get to
say you've used Snowflake.

---

## 6. No credentials needed

| Service | Why nothing is needed |
|---|---|
| PostgreSQL | Runs in Docker, credentials in `.env` already |
| Redis | Runs in Docker, no auth locally |
| Kafka | Runs in Docker (KRaft mode, no ZooKeeper) |
| Hadoop / HDFS | Runs in Docker under the `bigdata` profile |
| Remotive / Arbeitnow | Genuinely open public APIs, no key |

---

## The fastest possible start

One key gets you everything except Gmail:

```bash
# 1. get a free key at https://aistudio.google.com/apikey
# 2. put it in infra/.env as GEMINI_API_KEY
cd infra && docker compose restart agent-service
```

Add Adzuna when you want India/USA job data, and Google OAuth when you want inbox
tracking. Neither blocks anything else.

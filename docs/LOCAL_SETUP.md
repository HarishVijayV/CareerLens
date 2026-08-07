# Running CareerLens Locally

## Prerequisites

- Docker Desktop (you have 29.x — good)
- Python 3.11+ (you have 3.11.7 — good, run pipeline scripts outside Docker for speed)
- Node.js 18+ (you have 25.x — good, for the frontend)
- Git

## 1. Configure environment

```bash
cp infra/.env.example infra/.env
# open infra/.env and fill in at least: JWT_SECRET_KEY, and one LLM provider key
```

Generate a strong JWT secret:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## 2. Start the core app stack

```bash
cd infra
docker compose up -d --build
```

This starts: Postgres, Redis, Kafka, Adminer, and the five app services (gateway, auth,
agent, worker, notification). It does **not** start Hadoop/Airflow — those are heavy and only
needed when you're actively working on the data pipeline.

Check everything is healthy:

```bash
docker compose ps
```

- Gateway health check: http://localhost:8000/health
- Auth service docs: http://localhost:8001/docs
- Agent service docs: http://localhost:8002/docs
- Adminer (DB browser): http://localhost:8081 (server: `postgres`, user/pass from `.env`)

## 3. Start the big-data stack (only when working on the pipeline)

```bash
docker compose --profile bigdata up -d
```

- HDFS NameNode UI: http://localhost:9870
- Airflow UI: http://localhost:8080 (user/pass: `admin`/`admin`)

Stop it when you're done to save your machine's resources:

```bash
docker compose --profile bigdata down
```

## 4. Run pipeline scripts (outside Docker, faster for iteration)

```bash
cd pipeline
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt

python ingestion/generate_synthetic_data.py --rows 100000 --out data/raw/postings.jsonl
python spark_jobs/etl_clean_jobs.py --input data/raw/postings.jsonl --output data/curated/postings.parquet
python spark_jobs/mllib_salary_model.py --input data/curated/postings.parquet
python mapreduce_demo/benchmark_compare.py --input data/raw/postings.jsonl
```

## 5. Run the frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000

## Common issues

| Symptom | Likely cause | Fix |
|---|---|---|
| `docker compose` says "port already allocated" | Something else is using 5432/6379/8000 etc. | Change the port in `.env` / compose file, or stop the other process |
| Services can't reach postgres/redis | They started before postgres/redis were ready | We use `depends_on: condition: service_healthy` — if this still happens, `docker compose restart <service>` |
| Airflow webserver keeps restarting | `airflow-init` hasn't finished migrating the DB yet | Wait ~30s, check `docker compose logs airflow-init` |
| Spark job runs out of memory | Default local Spark session memory is small | Set `--driver-memory 4g` (see comments in the Spark scripts) or reduce `--rows` |

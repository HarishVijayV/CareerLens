# The Project, In Plain English

## The pitch (30 seconds)

"I built a platform that ingests job postings at scale — millions of rows, processed with
Hadoop/Spark like a real data engineering pipeline — cleans and analyzes them, and then a team
of AI agents uses that data to match my resume against real jobs, tailor it automatically, and
track my applications by reading my inbox. It's built as microservices with real auth,
caching, and a CI/CD pipeline, the way a company would actually ship it — not a notebook."

## The longer version, piece by piece

1. **Data engineering pipeline** — job postings (real, from public job-board APIs, plus a
   synthetic generator to push volume up to millions of rows) land in a raw data lake (HDFS
   locally, S3-equivalent in the cloud). PySpark cleans, deduplicates, and extracts structured
   fields (skills, salary, location) from messy text. One aggregation is also implemented as a
   raw MapReduce job so I can benchmark it against the Spark version — this is the direct
   sequel to my original "15M+ records, Hadoop/Spark, 40% faster" resume line, except now I
   have my own numbers, not inherited ones.

2. **Warehouse + analytics** — curated results load into Postgres (serving the live app) and
   Snowflake (for large-scale historical analytics). Tables are modeled as a proper star
   schema. dbt handles transformations and runs automated data-quality tests.

3. **Agentic AI copilot** — a planner agent decides what you're asking for and hands off to
   sub-agents: one extracts required skills from a job description, one scores your resume
   against a job, one rewrites specific resume bullets/keywords for that job, one reads your
   Gmail (via OAuth) and classifies application-related emails (applied / rejected / interview
   / offer), and one summarizes your whole application funnel — including which resume
   version actually gets more replies. Built twice: once as a hand-rolled orchestrator (to
   prove I understand tool-calling from first principles) and once in LangGraph (to show I can
   also use the industry-standard framework).

4. **Real product plumbing** — JWT + refresh tokens + session cookies for auth, Redis for
   caching and rate limiting, Kafka for event-driven bits (new posting scraped → event →
   worker reacts), RBAC, and the standard security list (CORS, CSRF, input validation, hashed
   + salted passwords).

5. **DevOps** — Docker Compose locally, GitHub Actions for CI/CD, and a clear path to
   Kubernetes + a real cloud provider (AWS/Azure/OCI) once the local version is solid.

## Answering the tricky interview questions

- **"Doesn't this already exist (Teal, Huntr, etc.)?"** — Yes. The point isn't novelty, it's
  that I designed and built the whole data + AI + backend stack myself and can explain every
  layer, which is what the interview is actually testing.
- **"Did you actually use it to find a job?"** — Answer honestly based on real usage. Even
  partial use ("I used it to track applications and tailor N resumes") is a fine, honest answer.
- **"Why Hadoop/MapReduce if Spark replaced it?"** — To prove I understand *why* Spark won,
  with my own benchmark numbers, not just a claim.

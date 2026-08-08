# Real Bugs Hit While Building This

Every bug below actually happened while getting this project running — none are
hypothetical. This is the most interview-valuable document in the repo: "tell me about a
bug you debugged" is a standard question, and these are real answers with real detail.

They're grouped by what each one teaches.

---

## 1. Security: the gateway let anyone impersonate any user

**What happened.** Downstream services trust an `X-User-Id` header set by the gateway
after it verifies the JWT. But the gateway was forwarding *all* client headers — so a
browser could simply send `X-User-Id: <someone else's id>` and the gateway would pass it
straight through. Any user could read any other user's profile.

**The fix.** The gateway now strips `X-User-Id` / `X-User-Role` from every incoming
request before setting its own from the verified token.

**The lesson.** Trusted-header authentication is a perfectly good pattern *and* a
critical vulnerability — the difference is entirely whether exactly one component can
write the header. If a value is trusted downstream, the boundary that produces it must
also destroy any client-supplied copy.

---

## 2. Auth: only one of two cookies survived login

**What happened.** Login sets two cookies (access + refresh). The gateway copied upstream
response headers with `dict(response.headers)` — and a dict can only hold one value per
key, so one `Set-Cookie` silently overwrote the other. Login appeared to work; token
refresh mysteriously failed later.

**The fix.** Relay headers with `.multi_items()` instead of `dict()`.

**The lesson.** HTTP headers are a multimap, not a map. Any code that flattens them to a
dict will silently corrupt `Set-Cookie`. The bug surfaced far from its cause, which is
what made it worth remembering.

---

## 3. Auth: `/api/profile` returned nothing, with no error

**What happened.** The gateway route was `/{service}/{path:path}`, which does not match a
bare `/api/profile`. FastAPI answered with a 307 redirect to `/api/profile/`, and
cross-origin redirects drop credentials — so the retried request was unauthenticated. The
logs read like an auth bug; it was a routing bug.

**The fix.** Register the bare `/{service}` form explicitly so no redirect occurs.

**The lesson.** A 307 is not free. In CORS + cookies territory, a redirect can silently
strip the credentials that make the request work.

---

## 4. Auth: signup crashed with "password cannot be longer than 72 bytes" — on a 12-character password

**What happened.** `passlib` has been unmaintained since 2020 and breaks against modern
`bcrypt` releases, raising a confusing error unrelated to the actual input.

**The fix.** Drop passlib, call `bcrypt` directly, and handle its real 72-byte limit
explicitly by SHA-256 pre-hashing the password first (so any length works, and nothing is
silently truncated).

**The lesson.** Two things. (a) The most-tutorialed library is not automatically the
maintained one — check the last release date. (b) bcrypt genuinely only reads 72 bytes;
naive truncation means two passwords sharing a 72-byte prefix would both unlock the
account. There's a regression test for exactly that in `tests/test_security.py`.

---

## 5. Spark: workers died with a socket timeout that had nothing to do with sockets

**What happened.** The Spark job failed at the Python-UDF stage with
`SocketTimeoutException: Accept timed out`. Buried further up: `Python was not found`.
On Windows, a bare `python` often resolves to the Microsoft Store alias stub, so Spark's
Python worker processes couldn't start, and the driver reported the symptom (no worker
connected) rather than the cause.

**The fix.** Pin `PYSPARK_PYTHON` and `PYSPARK_DRIVER_PYTHON` to `sys.executable`.

**The bigger fix.** Replace the Python UDF with native Spark SQL
(`regexp_replace(...).cast(...)`). A UDF forces every row out of the JVM into a Python
process and back; a native expression compiles into Spark's engine and never leaves the
JVM. Faster *and* one fewer failure mode.

**The lesson.** Prefer native expressions over UDFs whenever one exists — and read the
whole stack trace, because distributed systems usually report the symptom, not the cause.

---

## 6. Spark on Windows: reads and aggregations worked, every write failed

**What happened.** `HADOOP_HOME and hadoop.home.dir are unset`. Spark uses Hadoop's
filesystem layer even for plain local files, and on Windows that layer needs
`winutils.exe` + `hadoop.dll`. The job looked completely healthy right up until it tried
to save.

**The fix.** Install winutils and auto-detect `HADOOP_HOME` in `spark_common.py`.

**The lesson.** "It works until it writes" is a recognizable Windows-Spark signature.

---

## 7. Windows: `FileNotFoundError` on a file that visibly exists

**What happened.** Spark wrote its Parquet parts fine, `Path.glob()` listed them fine,
and `open()` then failed. Absolute paths here reach ~281 characters; Windows caps normal
paths at 260. The JVM uses long-path-aware APIs, Python's `open()` did not.

**The fix.** `pipeline/paths.py` — prefix absolute paths with `\\?\` to use the
extended-length API.

**The lesson.** When a file "exists but doesn't", check the path length before you
question your own eyes. (Also: deep project folders have real costs.)

---

## 8. Warehouse: 0 rows loaded, no error at all

**What happened.** Spark writes a *directory* of `part-*.parquet` files plus a `_SUCCESS`
marker. Handing that directory to `pandas.read_parquet` returned an empty DataFrame
instead of raising — the marker file confused it. The loader cheerfully reported success
after loading nothing.

**The fix.** Glob `part-*.parquet` explicitly.

**The lesson.** Silent empty results are more dangerous than crashes. Any load step
should assert it actually moved rows.

---

## 9. Warehouse: `invalid input syntax for type bigint: "184909.0"`

**What happened.** A column of whole numbers containing NULLs comes back from pandas as
`float64` (numpy ints can't hold NaN), so it serialized as `184909.0` and Postgres
rejected it for a `bigint` column.

**The fix.** Cast to pandas' nullable `Int64` dtype before writing the CSV.

**The lesson.** The int→float promotion around nulls is one of the most common data-
engineering papercuts there is.

---

## 10. Warehouse: the pipeline worked once, then broke on every re-run

**What happened.** `DROP TABLE raw.postings` failed with "other objects depend on it" —
dbt's staging models are VIEWS over `raw.*`. The first run passed because the views
didn't exist yet.

**The fix.** `DROP TABLE ... CASCADE`, which is safe here because dbt rebuilds every
model on each run and `raw.*` is owned solely by the loader.

**The lesson.** **A pipeline that hasn't been run twice hasn't been tested.**
Idempotency bugs hide behind the first successful run.

---

## 11. Data quality: asking a job API for "Data Engineer" returned "Sales Jedi"

**What happened.** Remotive's `search` parameter doesn't meaningfully filter. The first
ingestion run pulled back copywriting and graphic-design roles into a tech-jobs dataset.

**The first fix made it worse.** Filtering on title *or tags* still let
"Freelance Copywriter" through, because it carried a `data` tag.

**The final fix.** Narrow by category at the API, then filter on the **title** client-side
(exact match, or all significant words present in any order).

**The lesson.** Never assume a third-party filter works — verify what actually comes back.
Bad input data doesn't announce itself; it quietly poisons every downstream aggregate,
and a dashboard will happily chart nonsense. There are regression tests for this in
`tests/test_pipeline.py`.

---

## 12. Pipeline design: a third-party API returning nothing killed the entire run

**What happened.** The ingestion script exited non-zero when a job board returned no
matches, which aborted the whole pipeline — throwing away 150,000 rows of synthetic data
that had already been generated.

**The fix.** Warn loudly, exit clean, let the ETL process whatever raw files exist.

**The lesson.** Distinguish "this step found nothing" from "this step is broken". A
pipeline should degrade, not collapse, when one optional source is quiet.

---

## 13. FastAPI: a cache decorator broke every route it touched

**What happened.** Analytics endpoints started demanding query parameters literally named
`args` and `kwargs`. FastAPI builds each route's request model by *inspecting the handler's
signature* — and it was seeing the decorator's `(*args, **kwargs)` wrapper.

**The fix.** `@functools.wraps(fn)`, which sets `__wrapped__` so `inspect.signature`
follows through to the real function.

**The lesson.** `functools.wraps` isn't cosmetic in a framework that does signature
introspection — it's load-bearing.

---

## 14. A refactor broke a downstream job silently

**What happened.** Moving `required_skills` out of the postings table into a bridge table
(the right modeling call) removed a column the MLlib job depended on for `skill_count`.
Nothing caught it until the model job crashed mid-pipeline.

**The fix.** Compute `skill_count` in the ETL before dropping the array column, so
consumers get the scalar they actually need.

**The lesson.** Schema changes ripple. The reason it was caught at all is that the full
pipeline gets run end-to-end rather than step-by-step in isolation.

---

## What ties these together

Almost every bug here was found by **running the thing**, not by reading the code — and
several only appeared on the *second* run, or only at the *write* step, or only *across a
service boundary*. That's the real takeaway: code that has been written and code that has
been run are different states of done.

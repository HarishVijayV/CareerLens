from fastapi import FastAPI

from app.routers import analytics, jobs

app = FastAPI(title="CareerLens Jobs Service")
app.include_router(jobs.router)
app.include_router(analytics.router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "jobs-service"}

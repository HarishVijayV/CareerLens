from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app.db import Base, engine
from app.routers import applications, auth, google_oauth, profile, resume


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Dev-time convenience: create tables if missing. Phase 1+ should swap this for
    # Alembic migrations — auto-create is fine for a fresh local DB, never for data you
    # care about, because it can't express a CHANGE to an existing table.
    Base.metadata.create_all(bind=engine)

    with engine.begin() as conn:
        # gen_random_uuid() is used by the worker's raw-SQL inserts. It ships with
        # Postgres 13+ in pgcrypto; enabling it here means the worker doesn't have to.
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))

    yield


app = FastAPI(title="CareerLens Auth Service", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(profile.router)
app.include_router(google_oauth.router)
app.include_router(applications.router)
app.include_router(resume.router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "auth-service"}

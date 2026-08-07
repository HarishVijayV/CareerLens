from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import Base, engine
from app.routers import auth


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Dev-time convenience: create tables if they don't exist. In Phase 1+ swap this for
    # real migrations (Alembic) — auto-create is fine for a fresh local DB, not for
    # anything with real data you care about.
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="CareerLens Auth Service", lifespan=lifespan)
app.include_router(auth.router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "auth-service"}

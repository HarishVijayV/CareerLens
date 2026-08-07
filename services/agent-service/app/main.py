from fastapi import FastAPI

from app.routers import agents

app = FastAPI(title="CareerLens Agent Service")
app.include_router(agents.router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "agent-service"}

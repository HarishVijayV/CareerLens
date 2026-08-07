from fastapi import FastAPI

from app.routers import notifications

app = FastAPI(title="CareerLens Notification Service")
app.include_router(notifications.router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "notification-service"}

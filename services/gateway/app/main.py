from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.middleware.auth_middleware import AuthMiddleware
from app.middleware.logging_middleware import LoggingMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.routers import proxy

app = FastAPI(title="CareerLens Gateway")

# Order matters: middleware runs in REVERSE of the order added (last added = runs first).
# We want: CORS handled -> logging wraps everything -> auth verified -> THEN rate-limit
# by the now-known user id. So we add them bottom-up:
app.add_middleware(RateLimitMiddleware)   # runs last (needs user_id from AuthMiddleware)
app.add_middleware(AuthMiddleware)        # runs second
app.add_middleware(LoggingMiddleware)     # runs first (wants to time the whole request)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,   # required so the browser sends the httpOnly cookies
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(proxy.router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "gateway"}

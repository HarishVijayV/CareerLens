"""
Sliding-window rate limiting backed by Redis, keyed by user (falls back to client IP for
anonymous requests like login). Using Redis (not in-memory) matters the moment you run
more than one gateway replica — an in-memory counter would let each replica give the
attacker its own separate quota.
"""
import time

import redis.asyncio as redis
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import settings

_redis = redis.from_url(settings.redis_url, decode_responses=True)


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        identity = getattr(request.state, "user_id", None) or request.client.host
        key = f"ratelimit:{identity}:{int(time.time()) // settings.rate_limit_window_seconds}"

        current = await _redis.incr(key)
        if current == 1:
            await _redis.expire(key, settings.rate_limit_window_seconds)

        if current > settings.rate_limit_requests:
            return JSONResponse(
                {"detail": "Rate limit exceeded, slow down"},
                status_code=429,
                headers={"Retry-After": str(settings.rate_limit_window_seconds)},
            )

        return await call_next(request)

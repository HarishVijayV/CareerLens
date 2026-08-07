import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger("gateway.access")
logging.basicConfig(level=logging.INFO)


class LoggingMiddleware(BaseHTTPMiddleware):
    """Structured-ish request logging. In the cloud phase this is what a log shipper
    (Fluent Bit / CloudWatch / Log Analytics) would pick up for centralized logging."""

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        user_id = getattr(request.state, "user_id", "-")
        logger.info(
            "%s %s -> %s (%.1fms) user=%s",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            user_id,
        )
        return response

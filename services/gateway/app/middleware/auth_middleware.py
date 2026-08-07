"""
This is the ONE place in the whole system that verifies a JWT against the raw cookie.
Every downstream service (auth, agent, worker, notification) trusts the
`X-User-Id` / `X-User-Role` headers this middleware sets, instead of re-verifying the
cookie themselves. That's the actual point of a gateway: centralize a cross-cutting
concern instead of repeating it five times.

Routes that don't need a logged-in user (signup, login, health checks) are explicitly
exempted below — an allow-list, not a deny-list, so a newly added route is SECURE BY
DEFAULT and someone has to deliberately opt it out of auth, not forget to opt it in.
"""
import jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import settings

PUBLIC_PATHS = {
    "/health",
    "/docs",
    "/openapi.json",
    "/api/auth/signup",
    "/api/auth/login",
    "/api/auth/refresh",
    "/api/auth/google/callback",
}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        token = request.cookies.get("access_token")
        if not token:
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)

        try:
            claims = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        except jwt.PyJWTError:
            return JSONResponse({"detail": "Invalid or expired token"}, status_code=401)

        # Attach verified identity for downstream handlers/proxy to forward.
        request.state.user_id = claims["sub"]
        request.state.user_role = claims.get("role", "user")

        return await call_next(request)

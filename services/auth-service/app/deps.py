import jwt
from fastapi import Depends, HTTPException, Request, status

from app.core.security import decode_access_token


def get_current_claims(request: Request) -> dict:
    """Resolve the caller's identity, from either of two trusted sources.

    1. `X-User-Id` header — set by the GATEWAY after it verified the JWT, and also used
       for service-to-service calls (agent-service fetching a profile). This is safe only
       because the gateway strips any client-supplied X-User-Id before forwarding, so the
       header can never originate from a browser (see services/gateway/app/routers/proxy.py),
       and because this service is never published to the internet — only the gateway is.

    2. The `access_token` cookie — used when hitting this service directly, e.g. via
       /docs during development. The JWT signature is verified here.

    Being explicit about WHY a header is trustworthy is the whole game with trusted-header
    auth: it's a perfectly good pattern behind a gateway and a critical vulnerability
    without one.
    """
    user_id = request.headers.get("X-User-Id")
    if user_id:
        return {"sub": user_id, "role": request.headers.get("X-User-Role", "user")}

    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    try:
        return decode_access_token(token)
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")


def require_role(required_role: str):
    """Dependency factory for RBAC, e.g. `Depends(require_role('admin'))` on a route.
    The role travels inside the signed JWT, so a client can't tamper with it."""

    def _check(claims: dict = Depends(get_current_claims)) -> dict:
        if claims.get("role") != required_role:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
        return claims

    return _check

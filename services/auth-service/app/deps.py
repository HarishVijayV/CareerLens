import jwt
from fastapi import Depends, HTTPException, Request, status

from app.core.security import decode_access_token


def get_current_claims(request: Request) -> dict:
    """Reads the JWT out of the httpOnly cookie (never out of a header/localStorage —
    that's the whole point of using cookies here) and verifies it.

    Note: this service verifies its own cookie for local dev / direct testing via
    /docs. In the full system, the Gateway does this verification once and forwards the
    verified identity downstream in a trusted header — see docs/ARCHITECTURE.md."""
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        return decode_access_token(token)
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")


def require_role(required_role: str):
    """FastAPI dependency factory — e.g. `Depends(require_role('admin'))` on a route.
    This is the actual RBAC mechanism: the role travels inside the signed JWT, so it
    can't be tampered with client-side."""

    def _check(claims: dict = Depends(get_current_claims)) -> dict:
        if claims.get("role") != required_role:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
        return claims

    return _check

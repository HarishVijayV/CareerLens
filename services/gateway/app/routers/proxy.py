"""
The gateway does not re-implement business logic — it forwards to the right service and
attaches the verified identity as trusted headers. This is the "API Gateway" pattern:
one public entrypoint, N private services behind it that never need to be reachable from
the internet directly.
"""
import httpx
from fastapi import APIRouter, Request, Response

from app.core.config import settings

router = APIRouter(prefix="/api")

_SERVICE_MAP = {
    "auth": settings.auth_service_url,
    "agents": settings.agent_service_url,
    "notifications": settings.notification_service_url,
}


async def _forward(request: Request, service_base: str, downstream_path: str) -> Response:
    client = httpx.AsyncClient(base_url=service_base, timeout=30.0)
    headers = dict(request.headers)
    headers.pop("host", None)

    # trusted identity, set by AuthMiddleware after verifying the JWT — downstream
    # services read these headers instead of re-parsing the cookie.
    if hasattr(request.state, "user_id"):
        headers["X-User-Id"] = request.state.user_id
        headers["X-User-Role"] = request.state.user_role

    body = await request.body()
    upstream_response = await client.request(
        request.method, downstream_path, headers=headers, params=request.query_params, content=body
    )
    await client.aclose()

    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers=dict(upstream_response.headers),
    )


@router.api_route("/{service}/{downstream_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy(service: str, downstream_path: str, request: Request):
    service_base = _SERVICE_MAP.get(service)
    if not service_base:
        return Response(content=b'{"detail":"Unknown service"}', status_code=404, media_type="application/json")
    return await _forward(request, service_base, f"/{downstream_path}")

"""
The gateway implements no business logic — it forwards to the right service and attaches
the verified identity as trusted headers. That's the API Gateway pattern: one public
entrypoint, N private services behind it that never need to be reachable from the
internet at all.
"""
import httpx
from fastapi import APIRouter, Request, Response

from app.core.config import settings

router = APIRouter(prefix="/api")

# public segment -> (service base URL, path prefix on that service)
_SERVICE_MAP = {
    "auth": (settings.auth_service_url, "/auth"),
    # profile and applications are served by auth-service: they share an owner and a
    # database with identity, and splitting them would turn a join into a network call.
    "profile": (settings.auth_service_url, "/profile"),
    "applications": (settings.auth_service_url, "/applications"),
    "resume": (settings.auth_service_url, "/resume"),
    "agents": (settings.agent_service_url, "/agents"),
    "jobs": (settings.jobs_service_url, "/jobs"),
    "analytics": (settings.jobs_service_url, "/analytics"),
    "notifications": (settings.notification_service_url, "/notifications"),
}

# Hop-by-hop headers describe a single connection and must not be relayed to the next
# one (RFC 9110). Forwarding content-length in particular corrupts responses when the
# body gets re-encoded on the way out.
#
# x-user-id / x-user-role are in this list for a SECURITY reason, not a protocol one:
# downstream services trust those headers as proven identity, so if a browser were
# allowed to send its own, anyone could impersonate any user by typing a header. The
# gateway must strip whatever the client sent and set them itself from the verified JWT.
# Trusted-header auth is only safe when exactly one component can write the header.
_STRIP_REQUEST_HEADERS = {
    "host",
    "content-length",
    "connection",
    "transfer-encoding",
    "x-user-id",
    "x-user-role",
    "x-internal-call",
}
_STRIP_RESPONSE_HEADERS = {"content-length", "content-encoding", "connection", "transfer-encoding"}

# 60s was too short for the agent service, where one question is a chain of LLM calls:
# a team answer measured 90s and the user saw "the assistant call failed" for a request
# that was still running perfectly.
#
# The per-tool budget in agents/base.py is the real fix — this is the backstop, sized so
# a slow-but-working answer arrives rather than being cut off. Not unlimited: a genuinely
# stuck upstream must still fail rather than hold a connection open forever.
_client = httpx.AsyncClient(timeout=180.0)


_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]


# Two routes, because `/{service}/{path:path}` alone does NOT match a bare `/api/profile`
# — FastAPI answers that with a 307 redirect to `/api/profile/`, and a redirected
# cross-origin request quietly drops credentials, so the browser call fails in a way the
# logs make look like an auth bug. Registering the bare form explicitly avoids the
# redirect entirely.
@router.api_route("/{service}", methods=_METHODS)
async def proxy_root(service: str, request: Request):
    return await proxy(service, "", request)


@router.api_route("/{service}/{downstream_path:path}", methods=_METHODS)
async def proxy(service: str, downstream_path: str, request: Request):
    target = _SERVICE_MAP.get(service)
    if target is None:
        return Response(
            content=b'{"detail":"Unknown service"}', status_code=404, media_type="application/json"
        )

    base_url, prefix = target
    url = f"{base_url}{prefix}"
    if downstream_path:
        url = f"{url}/{downstream_path}"

    headers = {k: v for k, v in request.headers.items() if k.lower() not in _STRIP_REQUEST_HEADERS}

    # Identity comes from AuthMiddleware, which already verified the JWT signature.
    # Downstream services trust these headers and never re-parse the cookie themselves.
    if hasattr(request.state, "user_id"):
        headers["X-User-Id"] = request.state.user_id
        headers["X-User-Role"] = request.state.user_role

    upstream = await _client.request(
        request.method,
        url,
        headers=headers,
        params=request.query_params,
        content=await request.body(),
    )

    response = Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"),
    )

    # Relay Set-Cookie via raw headers, not dict(): a login response sets BOTH the access
    # and refresh cookies, and collapsing headers into a dict silently keeps only one —
    # which shows up later as "login works but refresh doesn't", a genuinely annoying bug.
    for key, value in upstream.headers.multi_items():
        if key.lower() not in _STRIP_RESPONSE_HEADERS and key.lower() != "content-type":
            response.headers.append(key, value)

    return response

"""
Google OAuth2 Authorization Code flow, for read-only Gmail access.

The flow, and why each step exists:

  1. /google/connect   — we redirect the user to Google with our client_id, the scopes we
                         want, and a random `state`. We never see their password.
  2. user consents     — entirely on Google's domain.
  3. /google/callback  — Google redirects back with a one-time `code` plus our `state`.
  4. server-side swap  — we exchange code + client_SECRET for tokens. This happens
                         server-to-server, so the secret and the tokens never reach the
                         browser. That's the entire point of the authorization-code flow
                         (as opposed to the deprecated implicit flow).

Two parameters that are easy to skip and shouldn't be:
  * `state` — a random value we generate, store, and require to match on return. Without
    it, an attacker can feed a victim a callback URL that links the ATTACKER's Google
    account to the victim's session (OAuth CSRF / login-confusion).
  * `access_type=offline` + `prompt=consent` — this is what makes Google issue a REFRESH
    token. Without it you get a one-hour access token and the background inbox sync stops
    working the moment the user closes the tab.
"""
import secrets
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import encrypt
from app.db import get_db
from app.deps import get_current_claims
from app.models import GoogleCredential

router = APIRouter(prefix="/auth/google", tags=["google-oauth"])

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

# Read-only, and only the two scopes actually needed. Requesting the narrowest scope that
# does the job is both good practice and practical: broad scopes make Google's review
# process much harder if this ever leaves testing mode.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
]

# state -> user_id. In-memory is fine for a single-instance dev app; with multiple gateway
# replicas this belongs in Redis with a short TTL, since the callback could land on a
# different instance than the one that started the flow.
_pending_states: dict[str, str] = {}


@router.get("/status")
def connection_status(claims: dict = Depends(get_current_claims), db: Session = Depends(get_db)):
    """Lets the UI show 'Connect Gmail' vs 'Connected as …' without guessing."""
    if not settings.google_oauth_configured:
        return {
            "configured": False,
            "connected": False,
            "message": "Google OAuth not configured — set GOOGLE_CLIENT_ID and "
            "GOOGLE_CLIENT_SECRET in infra/.env (see docs/CREDENTIALS.md).",
        }

    credential = (
        db.query(GoogleCredential).filter(GoogleCredential.user_id == claims["sub"]).first()
    )
    return {
        "configured": True,
        "connected": credential is not None,
        "google_email": credential.google_email if credential else None,
        "last_synced_at": credential.last_synced_at if credential else None,
    }


@router.get("/connect")
def connect(claims: dict = Depends(get_current_claims)):
    """Step 1 — hand the browser off to Google."""
    if not settings.google_oauth_configured:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED,
            "Google OAuth not configured. See docs/CREDENTIALS.md.",
        )

    state = secrets.token_urlsafe(32)
    _pending_states[state] = claims["sub"]

    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",   # ask for a refresh token
        "prompt": "consent",        # force re-consent so a refresh token is actually returned
        "state": state,
    }
    query = "&".join(f"{k}={httpx.QueryParams({k: v})[k]}" for k, v in params.items())
    return {"authorization_url": f"{GOOGLE_AUTH_URL}?{query}"}


@router.get("/callback")
def callback(
    code: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db),
):
    """Step 3-4 — Google sends the user back here with a one-time code."""
    user_id = _pending_states.pop(state, None)
    if user_id is None:
        # Unknown/replayed state — refuse. This is the CSRF protection actually doing its job.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired OAuth state")

    token_response = httpx.post(
        GOOGLE_TOKEN_URL,
        data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.google_redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=30.0,
    )
    if token_response.status_code != 200:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"Google token exchange failed: {token_response.text}"
        )

    tokens = token_response.json()
    refresh_token = tokens.get("refresh_token")
    access_token = tokens.get("access_token")

    # Google returns the scopes it ACTUALLY granted, which can be a subset of what we
    # asked for — the consent screen lets the user untick individual permissions. Storing
    # our requested list instead of this one is a real trap: the database then claims we
    # have Gmail access while every API call 403s, and the logs point nowhere useful.
    granted_scopes = tokens.get("scope", "")

    if "gmail.readonly" not in granted_scopes:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Gmail read permission was not granted — the 'Read your email messages and "
            "settings' checkbox was left unticked on the consent screen. Nothing was "
            "saved. Click Connect Gmail again and tick every permission.",
        )

    if not refresh_token:
        # Google only returns a refresh token on FIRST consent unless prompt=consent is
        # sent. Surfacing this clearly beats a mysterious sync failure days later.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Google did not return a refresh token. Revoke access at "
            "https://myaccount.google.com/permissions and reconnect.",
        )

    google_email = None
    try:
        userinfo = httpx.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15.0,
        )
        google_email = userinfo.json().get("email")
    except httpx.HTTPError:
        pass  # cosmetic only — never fail the connection over a display name

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=tokens.get("expires_in", 3600))

    credential = db.query(GoogleCredential).filter(GoogleCredential.user_id == user_id).first()
    if credential is None:
        credential = GoogleCredential(user_id=user_id)

    credential.encrypted_refresh_token = encrypt(refresh_token)
    credential.encrypted_access_token = encrypt(access_token) if access_token else None
    credential.access_token_expires_at = expires_at
    credential.scopes = granted_scopes
    credential.google_email = google_email

    db.add(credential)
    db.commit()

    # Back to the app, not a JSON blob — the user is in a browser mid-flow.
    return RedirectResponse(f"{settings.frontend_url}/applications?gmail=connected")


@router.delete("/disconnect")
def disconnect(claims: dict = Depends(get_current_claims), db: Session = Depends(get_db)):
    """Deleting the stored token is the part we control. Fully revoking access also
    requires the user to visit Google's permissions page — we tell them so rather than
    implying we did more than we did."""
    credential = (
        db.query(GoogleCredential).filter(GoogleCredential.user_id == claims["sub"]).first()
    )
    if credential:
        db.delete(credential)
        db.commit()

    return {
        "disconnected": True,
        "note": "Stored tokens deleted. To fully revoke, also visit "
        "https://myaccount.google.com/permissions",
    }

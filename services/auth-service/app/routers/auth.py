"""
The full login lifecycle. Read docs/AUTH_AND_SECURITY.md alongside this file — every
decision here (why a JWT AND a refresh token, why cookies not localStorage, why rotation
on refresh) is explained there in plain English.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    refresh_token_expiry,
    verify_password,
)
from app.db import get_db
from app.deps import get_current_claims
from app.models import RefreshToken, User
from app.schemas import LoginRequest, SignupRequest, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"


def _set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    common = dict(
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        domain=settings.cookie_domain if settings.cookie_domain != "localhost" else None,
    )
    response.set_cookie(
        ACCESS_COOKIE, access_token, max_age=settings.access_token_expire_minutes * 60, **common
    )
    response.set_cookie(
        REFRESH_COOKIE, refresh_token, max_age=settings.refresh_token_expire_days * 86400, **common
    )


def _issue_tokens(db: Session, user: User, response: Response) -> None:
    access_token = create_access_token(user.id, user.role)
    raw_refresh = generate_refresh_token()

    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(raw_refresh),
            expires_at=refresh_token_expiry(),
        )
    )
    db.commit()

    _set_auth_cookies(response, access_token, raw_refresh)


@router.post("/signup", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def signup(payload: SignupRequest, response: Response, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")

    user = User(email=payload.email, hashed_password=hash_password(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)

    _issue_tokens(db, user, response)
    return user


@router.post("/login", response_model=UserOut)
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    # Deliberately generic error for both "no such user" and "wrong password" — never
    # reveal which one it was, that alone lets an attacker enumerate valid emails.
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account disabled")

    _issue_tokens(db, user, response)
    return user


@router.post("/refresh", response_model=UserOut)
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    """Issues a brand-new access token from a still-valid refresh token, and ROTATES the
    refresh token in the same call (old one revoked, new one issued). Rotation is what
    lets you detect theft: a refresh token used a second time after rotation is a strong
    signal it leaked, and every session for that user could be force-revoked in response."""
    raw_refresh = request.cookies.get(REFRESH_COOKIE)
    if not raw_refresh:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No refresh token")

    token_hash = hash_refresh_token(raw_refresh)
    stored = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()

    if not stored or stored.revoked or stored.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token invalid or expired")

    user = db.query(User).filter(User.id == stored.user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account no longer active")

    stored.revoked = True  # rotation: this exact refresh token can never be used again
    db.add(stored)
    db.commit()

    _issue_tokens(db, user, response)
    return user


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(ACCESS_COOKIE)
    response.delete_cookie(REFRESH_COOKIE)
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(claims: dict = Depends(get_current_claims), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == claims["sub"]).first()
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user

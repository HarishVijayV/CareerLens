"""
Profile CRUD. GET creates an empty profile on first access rather than 404-ing, so the
frontend can always render the form without a "does it exist yet" branch — small choice,
but it removes a whole class of edge cases from the UI.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_claims
from app.models import UserProfile
from app.schemas import ProfileOut, ProfileUpdate

router = APIRouter(prefix="/profile", tags=["profile"])


def _get_or_create(db: Session, user_id: str) -> UserProfile:
    profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
    if profile is None:
        profile = UserProfile(user_id=user_id)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


@router.get("", response_model=ProfileOut)
def get_profile(claims: dict = Depends(get_current_claims), db: Session = Depends(get_db)):
    return _get_or_create(db, claims["sub"])


@router.patch("", response_model=ProfileOut)
def update_profile(
    payload: ProfileUpdate,
    claims: dict = Depends(get_current_claims),
    db: Session = Depends(get_db),
):
    profile = _get_or_create(db, claims["sub"])

    # exclude_unset means "only the fields the client actually sent" — without it,
    # omitted fields would arrive as None and silently WIPE existing values.
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)

    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


@router.get("/search-terms")
def get_search_terms(claims: dict = Depends(get_current_claims), db: Session = Depends(get_db)):
    """Consumed by the worker service when it runs a profile-driven job fetch."""
    profile = _get_or_create(db, claims["sub"])
    return {
        "terms": profile.as_search_terms(),
        "countries": [c.strip() for c in (profile.countries or "in,us").split(",") if c.strip()],
        "remote_only": profile.remote_only,
        "min_salary": profile.min_salary,
    }

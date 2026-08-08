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


@router.post("/from-resume")
def suggest_from_resume(
    claims: dict = Depends(get_current_claims), db: Session = Depends(get_db)
):
    """Read the user's ACTIVE resume and return the profile fields it implies.

    This SUGGESTS, it does not save. That distinction is the whole design:

    The profile drives which jobs get fetched from Adzuna and how every match is scored,
    so a wrong value here quietly poisons everything downstream — and unlike a bad chat
    reply, nobody would notice. An LLM reading a resume will occasionally decide a
    university name is an employer or that a course project is a job. Handing the user a
    filled-in form they can correct before saving keeps a human in the loop at the one
    point where being wrong is expensive and invisible.

    It also means this endpoint can never destroy hand-typed values, which the obvious
    implementation (extract and PATCH in one step) would do on every click.
    """
    import json
    import os

    import httpx

    from app.models import ResumeVersion

    version = (
        db.query(ResumeVersion)
        .filter(ResumeVersion.user_id == claims["sub"], ResumeVersion.is_active.is_(True))
        .first()
    )
    if not version or not (version.content_text or "").strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload a resume first — there's nothing to read.",
        )

    agent_url = os.getenv("AGENT_SERVICE_URL", "http://agent-service:8000")
    try:
        response = httpx.post(
            f"{agent_url}/agents/ask",
            # Naming the agent explicitly skips the planner: we know exactly which one we
            # want, so paying for a routing call to rediscover that would be waste.
            json={
                "message": version.content_text[:12000],
                "agent": "profile_extractor",
            },
            timeout=90.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not read the resume ({type(exc).__name__}). Is the LLM key set?",
        )

    answer = (response.json().get("answer") or "").strip()
    if answer.startswith("```"):
        answer = answer.split("```")[1].removeprefix("json").strip()

    try:
        extracted = json.loads(answer)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The resume reader returned something unreadable. Try again.",
        )

    def _joined(value) -> str | None:
        """The model returns lists; the profile stores comma-separated text."""
        if isinstance(value, list):
            cleaned = [str(v).strip() for v in value if str(v).strip()]
            return ", ".join(cleaned) or None
        return (str(value).strip() or None) if value else None

    return {
        "source_version": version.label,
        "suggestion": {
            "full_name": _joined(extracted.get("full_name")),
            "headline": _joined(extracted.get("headline")),
            "skills": _joined(extracted.get("skills")),
            "target_roles": _joined(extracted.get("target_roles")),
            "seniority": _joined(extracted.get("seniority")),
            "preferred_locations": _joined(extracted.get("preferred_locations")),
            # countries is comma-separated with NO spaces — it goes straight into Adzuna
            # country codes, where "in, us" would produce a request for a country called
            # " us" and silently return nothing.
            "countries": (
                ",".join(
                    str(c).strip().lower()
                    for c in extracted.get("countries", [])
                    if str(c).strip()
                )
                or None
            ),
        },
    }


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

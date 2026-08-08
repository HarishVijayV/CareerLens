import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, default="user", nullable=False)  # user | admin
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # set after Google OAuth login; null for plain email/password users
    google_sub: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    profile: Mapped["UserProfile | None"] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )


class RefreshToken(Base):
    """Only the HASH of each refresh token is stored — same principle as passwords. Rows
    here are the source of truth for "is this session still valid", which is exactly what
    a stateless JWT cannot tell you on its own."""

    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    user: Mapped["User"] = relationship(back_populates="refresh_tokens")


class UserProfile(Base):
    """What the user tells us about themselves — drives both job SEARCH (these values
    become query parameters to the job APIs, so you get relevant postings instead of
    every posting on the internet) and job RANKING (the resume-matcher agent scores
    against these instead of guessing)."""

    __tablename__ = "user_profiles"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)

    full_name: Mapped[str | None] = mapped_column(String, nullable=True)
    headline: Mapped[str | None] = mapped_column(String, nullable=True)  # "Data Engineer"

    # Stored as comma-separated text rather than a Postgres array so the same models work
    # unchanged if this ever moves to another engine — the same portability reasoning
    # behind the bridge table in the warehouse (see docs/DATA_ENGINEERING.md).
    skills: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_roles: Mapped[str | None] = mapped_column(Text, nullable=True)

    countries: Mapped[str] = mapped_column(String, default="in,us")  # Adzuna country codes
    preferred_locations: Mapped[str | None] = mapped_column(Text, nullable=True)
    remote_only: Mapped[bool] = mapped_column(Boolean, default=False)

    min_salary: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seniority: Mapped[str | None] = mapped_column(String, nullable=True)

    resume_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    resume_latex: Mapped[str | None] = mapped_column(Text, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    user: Mapped["User"] = relationship(back_populates="profile")

    def as_search_terms(self) -> list[str]:
        """Turns the profile into the keyword list handed to the job-board APIs."""
        raw = f"{self.target_roles or ''},{self.headline or ''}"
        return [term.strip() for term in raw.split(",") if term.strip()]

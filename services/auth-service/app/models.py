import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text
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


class ResumeVersion(Base):
    """Every saved state of a resume, kept rather than overwritten.

    Versioning is not a nicety here — it's what makes the whole feature safe and
    measurable:
      * safety — an AI rewrite can never destroy the original; you can always go back
      * measurement — Application.resume_version points at one of these rows, so
        "which version got more replies" becomes a real query instead of a guess

    Both `content_text` and `content_latex` are stored. LaTeX is the source of truth when
    present (it's what compiles to the PDF you send); the plain text is what the agents
    reason over, because feeding LaTeX markup to an LLM wastes tokens on syntax and
    invites it to mangle the formatting.
    """

    __tablename__ = "resume_versions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)

    label: Mapped[str] = mapped_column(String, nullable=False)  # "v1-original", "tailored-acme"
    content_text: Mapped[str] = mapped_column(Text, default="")
    content_latex: Mapped[str | None] = mapped_column(Text, nullable=True)

    # tex | pdf | docx | txt — what was originally uploaded
    source_format: Mapped[str] = mapped_column(String, default="txt")
    # upload | ai_tailored | manual_edit
    origin: Mapped[str] = mapped_column(String, default="upload")

    # set when an agent produced this version, so provenance is never ambiguous
    tailored_for_posting_id: Mapped[str | None] = mapped_column(String, nullable=True)
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # The bytes as uploaded. Kept so a PDF resume can be shown AS a PDF — extraction is
    # lossy and one-way, so without the original there is nothing faithful to display.
    original_file: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    original_filename: Mapped[str | None] = mapped_column(String, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    user: Mapped["User"] = relationship()


class GoogleCredential(Base):
    """Google OAuth tokens for Gmail access.

    The refresh token is what lets the WORKER poll your inbox on a schedule while you're
    not sitting at the browser — that's the whole reason offline access exists. It never
    touches the frontend: the browser only ever sees a one-time authorization code, and
    the code→token exchange happens server-side.

    Stored encrypted at rest (see app/core/crypto.py). A leaked database should not equal
    a leaked inbox.
    """

    __tablename__ = "google_credentials"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)

    encrypted_refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    scopes: Mapped[str] = mapped_column(Text, default="")
    google_email: Mapped[str | None] = mapped_column(String, nullable=True)

    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    user: Mapped["User"] = relationship()


class Application(Base):
    """One job application and its current status.

    This is the fact table of the whole job-hunt story: it's what makes the funnel
    (applied → interview → offer) and the resume-version A/B comparison computable rather
    than a feeling.
    """

    __tablename__ = "applications"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)

    company: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str | None] = mapped_column(String, nullable=True)
    posting_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # applied | rejected | interview_invite | offer | recruiter_outreach
    status: Mapped[str] = mapped_column(String, default="applied", nullable=False)

    # Which resume produced this outcome — the key to answering "is version B working
    # better than version A", which is the genuinely useful question.
    resume_version: Mapped[str | None] = mapped_column(String, nullable=True)

    source: Mapped[str] = mapped_column(String, default="email")  # email | manual
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    events: Mapped[list["ApplicationEvent"]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )


class ApplicationEvent(Base):
    """Append-only history of status changes.

    Storing events rather than only the current status is what makes time-based questions
    answerable later — "how long until companies reply?", "did response rates change after
    I rewrote my resume?" A single mutable status column throws that history away.
    """

    __tablename__ = "application_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), nullable=False)

    status: Mapped[str] = mapped_column(String, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Gmail's own message id — the idempotency key. Re-syncing the same inbox must not
    # create duplicate events, and this unique constraint is what guarantees that at the
    # database level rather than hoping the code remembers to check.
    gmail_message_id: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)

    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    application: Mapped["Application"] = relationship(back_populates="events")

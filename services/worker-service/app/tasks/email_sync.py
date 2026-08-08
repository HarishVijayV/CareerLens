"""
Inbox → classified application status. The whole point of the email feature.

Flow:
  1. Read the user's stored Google refresh token (encrypted at rest)
  2. Ask Gmail for candidate messages using ITS OWN search syntax (cheap server-side filter)
  3. Send each one to the email_classifier agent
  4. Upsert into applications + append an event

Runs in the worker, not in a request, because it's slow and bursty: N Gmail round-trips
plus N LLM calls. Nobody should wait on that behind an HTTP request, and it must not fall
over if one message fails.
"""
import logging
import os

import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.celery_app import celery_app
from app.crypto import try_decrypt
from app.gmail_client import GmailClient

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+psycopg://careerlens:change_me@postgres:5432/careerlens"
)
AGENT_SERVICE_URL = os.getenv("AGENT_SERVICE_URL", "http://agent-service:8000")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)

# Gmail search syntax. Narrowing here means we download tens of messages instead of
# thousands, and the LLM only ever sees plausible candidates — the cheapest filter is the
# one that runs before your code does.
# Gmail search syntax. Two lessons are baked into this query:
#
# 1. Single generic words are useless. An earlier version matched subject:(application OR
#    offer) and returned a Red Hat API-key notice, a Samsung sale, and a GitHub OAuth
#    alert — every one a false positive. "application" and "offer" are simply common
#    English words. Multi-word phrases carry the job context; single words don't.
#
# 2. The LLM classifier is a safety net, not a filter. It correctly rejected all that
#    noise, but each rejection still cost an API call. Filtering precisely here is a cost
#    control: the cheapest classification is the one you never make.
#
# ATS senders are the highest-signal indicator available — nobody receives Greenhouse or
# Lever mail by accident.
ATS_SENDERS = (
    "greenhouse.io OR lever.co OR myworkday.com OR workday.com OR ashbyhq.com OR "
    "smartrecruiters.com OR icims.com OR taleo.net OR successfactors.com OR "
    "jobvite.com OR breezy.hr OR workable.com OR bamboohr.com OR hire.google.com"
)

# SUBJECT-only, and multi-word only. Two failed attempts got us here:
#   v1  subject:(application OR offer)  -> 4 hits, all false (API keys, a Samsung sale)
#   v2  v1 + the same phrases matched in the BODY -> 20 hits, MORE noise: any newsletter
#       containing "unfortunately" or "your application" anywhere qualified
# Body matching sounds more thorough and is strictly worse; a marketing email mentions
# these words in passing, while a real ATS mail puts them in the SUBJECT.
JOB_PHRASES = (
    '"thank you for applying" OR "application received" OR "application status" OR '
    '"we received your application" OR "your application" OR "interview invitation" OR '
    '"schedule an interview" OR "interview request" OR "offer letter" OR '
    '"application update" OR "regarding your application"'
)

# How far back to look. 30 days by default, down from 180.
#
# The window is the single biggest driver of sync time: it multiplies BOTH the Gmail
# round-trips and the LLM calls, and a 6-month window re-scans the same months on every
# run for candidates that were almost all classified the first time.
#
# 30 days also matches how the feature is actually used. Application status moves within
# weeks — an ATS mail older than a month has already been superseded by a rejection, an
# offer, or silence. Anything genuinely older is already in the DB from a previous sync,
# because processed messages are deduped on gmail_message_id and never re-classified.
#
# Overridable per call and by env var, because the FIRST sync on a new account is the one
# case where a wider window is right — there's no history to have caught the older mail.
DEFAULT_LOOKBACK_DAYS = int(os.getenv("GMAIL_LOOKBACK_DAYS", "30"))


def build_gmail_query(lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> str:
    """Compose the Gmail search. Built as a function so the window is a parameter rather
    than baked into a module constant that can only be changed by editing code."""
    return (
        f"newer_than:{lookback_days}d ("
        f"from:({ATS_SENDERS}) "
        f"OR subject:({JOB_PHRASES})"
        f")"
    )

# Only these statuses represent a real application. The classifier is explicitly allowed
# to say "not_job_related", and we must honour that rather than forcing every newsletter
# into the funnel.
TRACKED = {"applied", "rejected", "interview_invite", "offer"}


def _classify(email: dict) -> dict | None:
    """Ask the email_classifier agent to label one message."""
    prompt = (
        f"Subject: {email['subject']}\n"
        f"From: {email['from']}\n"
        f"Date: {email['date']}\n\n"
        f"{email['body'][:2000]}"
    )
    try:
        response = httpx.post(
            f"{AGENT_SERVICE_URL}/agents/ask",
            json={"message": prompt, "agent": "email_classifier"},
            timeout=60.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("classifier call failed for %s: %s", email["id"], exc)
        return None

    import json

    answer = (response.json().get("answer") or "").strip()
    # Models often wrap JSON in ``` fences despite instructions — strip them rather than
    # failing, since the content is usually fine.
    if answer.startswith("```"):
        answer = answer.split("```")[1].removeprefix("json").strip()

    try:
        return json.loads(answer)
    except json.JSONDecodeError:
        logger.warning("unparseable classifier output for %s: %.120s", email["id"], answer)
        return None


@celery_app.task(name="app.tasks.email_sync.sync_inbox")
def sync_inbox(
    user_id: str,
    max_messages: int = 40,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict:
    if not (GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET):
        return {"status": "not_configured", "detail": "GOOGLE_CLIENT_ID/SECRET not set"}

    session = SessionLocal()
    try:
        row = session.execute(
            text("SELECT encrypted_refresh_token FROM google_credentials WHERE user_id = :uid"),
            {"uid": user_id},
        ).first()
        if not row:
            return {"status": "not_connected", "detail": "User has not connected Gmail"}

        refresh_token = try_decrypt(row[0])
        if not refresh_token:
            return {"status": "decrypt_failed", "detail": "Re-connect Gmail (encryption key changed?)"}

        client = GmailClient(refresh_token, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET)
        query = build_gmail_query(lookback_days)
        message_ids = client.list_message_ids(query, max_results=max_messages)
        logger.info(
            "gmail sync user=%s lookback=%dd candidates=%d",
            user_id,
            lookback_days,
            len(message_ids),
        )

        # Skip messages already processed. This is why gmail_message_id is UNIQUE on
        # application_events: re-running a sync must never duplicate history, and the DB
        # enforces that even if this check races.
        seen = {
            r[0]
            for r in session.execute(
                text("SELECT gmail_message_id FROM application_events WHERE gmail_message_id IS NOT NULL")
            ).all()
        }

        processed = skipped = 0

        for message_id in message_ids:
            if message_id in seen:
                skipped += 1
                continue

            try:
                email = client.get_message(message_id)
            except httpx.HTTPError as exc:
                logger.warning("fetch failed %s: %s", message_id, exc)
                continue

            classification = _classify(email)
            if not classification:
                continue

            category = classification.get("category")
            company = (classification.get("company") or "").strip()

            if category not in TRACKED or not company:
                skipped += 1
                continue

            role = classification.get("role")

            # Upsert on (user, company): one application per company per role, updated as
            # its status progresses, rather than a new row per email in the thread.
            existing = session.execute(
                text(
                    "SELECT id, status FROM applications "
                    "WHERE user_id = :uid AND lower(company) = lower(:company) LIMIT 1"
                ),
                {"uid": user_id, "company": company},
            ).first()

            if existing:
                application_id, current_status = existing
                # Never regress a status: an "applied" confirmation arriving after an
                # interview invite must not knock the application back a stage. Ordering
                # by email date is unreliable (delivery delays), so rank explicitly.
                rank = {"applied": 0, "recruiter_outreach": 0, "interview_invite": 1, "offer": 2, "rejected": 3}
                if rank.get(category, 0) > rank.get(current_status, 0):
                    session.execute(
                        text("UPDATE applications SET status = :s, updated_at = now() WHERE id = :id"),
                        {"s": category, "id": application_id},
                    )
            else:
                application_id = session.execute(
                    text(
                        "INSERT INTO applications (id, user_id, company, role, status, source, applied_at, updated_at) "
                        "VALUES (gen_random_uuid()::text, :uid, :company, :role, :status, 'email', now(), now()) "
                        "RETURNING id"
                    ),
                    {"uid": user_id, "company": company, "role": role, "status": category},
                ).scalar()

            session.execute(
                text(
                    "INSERT INTO application_events (id, application_id, status, detail, gmail_message_id, occurred_at) "
                    "VALUES (gen_random_uuid()::text, :app_id, :status, :detail, :msg_id, now()) "
                    "ON CONFLICT (gmail_message_id) DO NOTHING"
                ),
                {
                    "app_id": application_id,
                    "status": category,
                    "detail": email["subject"][:200],
                    "msg_id": message_id,
                },
            )
            processed += 1

        session.execute(
            text("UPDATE google_credentials SET last_synced_at = now() WHERE user_id = :uid"),
            {"uid": user_id},
        )
        session.commit()

        return {
            "status": "ok",
            "candidates": len(message_ids),
            "processed": processed,
            "skipped": skipped,
        }

    except Exception as exc:  # noqa: BLE001
        session.rollback()
        logger.exception("gmail sync failed for %s", user_id)
        return {"status": "error", "detail": str(exc)}
    finally:
        session.close()

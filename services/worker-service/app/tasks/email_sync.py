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
GMAIL_QUERY = (
    'newer_than:90d ('
    'subject:(application OR interview OR "thank you for applying" OR candidate OR '
    'recruit OR offer OR position OR role) '
    'OR from:(greenhouse.io OR lever.co OR workday.com OR ashbyhq.com OR smartrecruiters.com)'
    ')'
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
def sync_inbox(user_id: str, max_messages: int = 40) -> dict:
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
        message_ids = client.list_message_ids(GMAIL_QUERY, max_results=max_messages)
        logger.info("gmail sync user=%s candidates=%d", user_id, len(message_ids))

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

"""
Kafka consumer: `posting.discovered` -> notify users whose profile matches.

This is the consumer that JUSTIFIES Kafka in this project. It is completely independent
of the warehouse loader that consumes the same topic:
  * different failure modes — a broken notifier must not stop analytics data landing
  * different scaling — notification is bursty, loading is steady
  * different ownership — neither knows the other exists

The producer (pipeline/ingestion/job_apis.py) calls neither of them by name. Adding a
third consumer later means deploying it, not editing ingestion. That decoupling is the
whole argument for a broker; without more than one consumer it wouldn't be worth it, and
pipeline/events.py says so explicitly.

Run:
    python -m app.consumers.match_notifier
"""
import json
import logging
import os
import signal
import sys

import httpx
from sqlalchemy import create_engine, text

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("match_notifier")

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+psycopg://careerlens:change_me@postgres:5432/careerlens"
)
NOTIFICATION_URL = os.getenv("NOTIFICATION_SERVICE_URL", "http://notification-service:8000")

TOPIC = "posting.discovered"
GROUP_ID = "match-notifier"
MIN_SKILL_OVERLAP = 2

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
_running = True


def _load_profiles() -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT p.user_id, u.email, p.skills, p.target_roles "
                "FROM user_profiles p JOIN users u ON u.id = p.user_id "
                "WHERE p.skills IS NOT NULL AND p.skills <> ''"
            )
        ).all()

    return [
        {
            "user_id": r[0],
            "email": r[1],
            "skills": {s.strip().lower() for s in (r[2] or "").split(",") if s.strip()},
            "roles": [t.strip().lower() for t in (r[3] or "").split(",") if t.strip()],
        }
        for r in rows
    ]


def _matches(profile: dict, posting: dict) -> tuple[bool, list[str]]:
    posting_skills = {s.strip().lower() for s in posting.get("required_skills", []) if s}
    overlap = sorted(profile["skills"] & posting_skills)

    title = (posting.get("title") or "").lower()
    role_match = any(role in title for role in profile["roles"])

    # Either a strong skill overlap OR an explicit target-role match. Requiring both would
    # miss roles titled differently than expected; requiring neither would spam.
    return (len(overlap) >= MIN_SKILL_OVERLAP or role_match), overlap


def _notify(profile: dict, posting: dict, overlap: list[str]) -> None:
    body = (
        f"New posting matching your profile:\n\n"
        f"{posting.get('title')} at {posting.get('company')}\n"
        f"Region: {posting.get('region')}\n"
        f"Matching skills: {', '.join(overlap) or '(role title match)'}\n"
    )
    try:
        httpx.post(
            f"{NOTIFICATION_URL}/notifications/email",
            json={"to": profile["email"], "subject": f"Job match: {posting.get('title')}", "body": body},
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        # A failed notification must not crash the consumer or block the offset commit
        # for everyone else — log it and move on.
        logger.warning("notify failed for %s: %s", profile["email"], exc)


def main() -> None:
    try:
        from kafka import KafkaConsumer
    except ImportError:
        logger.error("kafka-python not installed")
        sys.exit(1)

    consumer = KafkaConsumer(
        TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP.split(","),
        # group_id is what makes this a consumer GROUP: Kafka tracks this group's offset
        # separately from every other group, so the warehouse loader reading the same
        # topic gets its own independent position. That is precisely how one event
        # reaches several consumers without them coordinating.
        group_id=GROUP_ID,
        value_deserializer=lambda v: json.loads(v.decode()),
        auto_offset_reset="latest",
        # Commit only after processing, so a crash mid-message reprocesses rather than
        # silently dropping it. At-least-once, which suits notifications (a duplicate
        # email is survivable; a missed match is not).
        enable_auto_commit=False,
        consumer_timeout_ms=1000,
    )

    logger.info("listening on %s as group '%s'", TOPIC, GROUP_ID)

    profiles = _load_profiles()
    logger.info("loaded %d profiles", len(profiles))
    messages_since_reload = 0

    while _running:
        for message in consumer:
            posting = message.value
            for profile in profiles:
                matched, overlap = _matches(profile, posting)
                if matched:
                    logger.info(
                        "match: %s <- %s (%s)", profile["email"], posting.get("title"), overlap
                    )
                    _notify(profile, posting, overlap)

            consumer.commit()

            messages_since_reload += 1
            if messages_since_reload >= 100:
                profiles = _load_profiles()   # pick up profile edits without a restart
                messages_since_reload = 0

    consumer.close()
    logger.info("shut down cleanly")


def _handle_signal(signum, frame):
    """Graceful shutdown: finish the current message and commit, rather than dying
    mid-batch and reprocessing on restart."""
    global _running
    logger.info("signal %s received — shutting down", signum)
    _running = False


if __name__ == "__main__":
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    main()

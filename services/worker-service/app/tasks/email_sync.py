"""
Phase 6 (docs/ROADMAP.md): polls Gmail (read-only OAuth scope, see
docs/AUTH_AND_SECURITY.md's OAuth section) for application-related messages, and hands
each one to the agent-service's email-classifier sub-agent to label
(applied/rejected/interview/offer) and update the application-tracking table. Stubbed
for now so the Celery beat schedule and task-dispatch plumbing can be wired and tested
before Gmail OAuth exists.
"""
import logging

from app.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.email_sync.sync_inbox")
def sync_inbox(user_id: str) -> dict:
    logger.info("sync_inbox(%s): placeholder — wire to Gmail API + email_classifier agent", user_id)
    return {"status": "not_yet_wired", "user_id": user_id, "emails_processed": 0}

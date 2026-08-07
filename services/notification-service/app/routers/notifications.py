"""
Deliberately the smallest service in the system — it exists so a flaky email/SMS
provider can never take down login, agents, or the pipeline. Kept separate == kept
replaceable: swapping SendGrid for SES later touches only this one service.
"""
from fastapi import APIRouter
from pydantic import BaseModel, EmailStr

router = APIRouter(prefix="/notifications", tags=["notifications"])


class EmailNotification(BaseModel):
    to: EmailStr
    subject: str
    body: str


@router.post("/email")
def send_email(notification: EmailNotification):
    # Phase 6 (docs/ROADMAP.md): wire to a real provider (SES/SendGrid). Logged instead
    # of sent for now so the rest of the system can call this endpoint today without
    # needing real provider credentials yet.
    print(f"[notification-service] would send email to {notification.to}: {notification.subject}")
    return {"status": "logged_not_sent", "to": notification.to}

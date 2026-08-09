"""
In-app notifications — the bell in the top bar.

Lives in auth-service because this is per-user data, and auth-service already owns
everything else that belongs to a user. Splitting it out would mean a second service that
needs the same user table and the same auth.

The WRITE path is separate from the read path on purpose. Users read their own
notifications with a normal cookie; the Kafka consumer writes them with an internal
header, because it acts on behalf of a user it is not logged in as. That distinction is
the same one the gateway enforces: a client can never assert who it is.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_claims
from app.models import Notification

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    id: str
    kind: str
    title: str
    body: str | None
    link: str | None
    posting_id: str | None
    read: bool
    created_at: datetime

    class Config:
        from_attributes = True


class NotificationCreate(BaseModel):
    user_id: str
    title: str
    body: str | None = None
    link: str | None = None
    posting_id: str | None = None
    kind: str = "job_match"


@router.get("", response_model=list[NotificationOut])
def list_notifications(
    unread_only: bool = Query(False),
    limit: int = Query(30, le=100),
    claims: dict = Depends(get_current_claims),
    db: Session = Depends(get_db),
):
    query = db.query(Notification).filter(Notification.user_id == claims["sub"])
    if unread_only:
        query = query.filter(Notification.read.is_(False))
    return query.order_by(Notification.created_at.desc()).limit(limit).all()


@router.get("/unread-count")
def unread_count(
    claims: dict = Depends(get_current_claims), db: Session = Depends(get_db)
):
    """Just the number, for the badge.

    Its own endpoint because the bell polls this every 60 seconds and only needs an
    integer — fetching 30 full rows to count them would move real payload on a timer for
    no reason.
    """
    count = (
        db.query(Notification)
        .filter(Notification.user_id == claims["sub"], Notification.read.is_(False))
        .count()
    )
    return {"unread": count}


@router.post("/read-all")
def mark_all_read(
    claims: dict = Depends(get_current_claims), db: Session = Depends(get_db)
):
    updated = (
        db.query(Notification)
        .filter(Notification.user_id == claims["sub"], Notification.read.is_(False))
        .update({"read": True}, synchronize_session=False)
    )
    db.commit()
    return {"marked_read": updated}


@router.post("/{notification_id}/read", response_model=NotificationOut)
def mark_read(
    notification_id: str,
    claims: dict = Depends(get_current_claims),
    db: Session = Depends(get_db),
):
    notification = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.user_id == claims["sub"])
        .first()
    )
    if not notification:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    notification.read = True
    db.commit()
    db.refresh(notification)
    return notification


@router.post("/internal", response_model=NotificationOut, status_code=status.HTTP_201_CREATED)
def create_internal(
    payload: NotificationCreate,
    x_internal_call: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Called by the Kafka consumer, never by a browser.

    The gateway strips `X-Internal-Call` from anything a client sends, so this header can
    only be present on a request that originated inside the cluster — the same mechanism
    that stops a client asserting `X-User-Id`.

    Duplicates are IGNORED rather than raising: every pipeline run republishes events for
    postings the user has already been told about, and the honest fix for "tell them once"
    is a unique constraint, not the consumer trying to remember what it sent last week.
    """
    if not x_internal_call:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Internal only")

    if payload.posting_id:
        existing = (
            db.query(Notification)
            .filter(
                Notification.user_id == payload.user_id,
                Notification.posting_id == payload.posting_id,
            )
            .first()
        )
        if existing:
            return existing

    notification = Notification(
        user_id=payload.user_id,
        kind=payload.kind,
        title=payload.title,
        body=payload.body,
        link=payload.link,
        posting_id=payload.posting_id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)
    return notification

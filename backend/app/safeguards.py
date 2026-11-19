"""Protection for a publicly hosted instance: an access code for write actions and daily
limits on AI processing, so a shared link can't run up the owner's AI bill."""

import secrets
from datetime import datetime, time, timezone

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import UsageEvent


def client_ip(request: Request) -> str:
    # Hosting platforms put the real visitor IP first in X-Forwarded-For
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "unknown")[:64]


def require_access_code(x_access_code: str | None = Header(default=None)) -> None:
    """Dependency for write endpoints. No-op when UPLOAD_ACCESS_CODE is not configured."""
    expected = get_settings().upload_access_code
    if not expected:
        return
    if not x_access_code:
        raise HTTPException(401, "An access code is needed to upload or change documents. Ask the owner for it.")
    if not secrets.compare_digest(x_access_code.strip(), expected):
        raise HTTPException(403, "That access code isn't right.")


def _start_of_today() -> datetime:
    return datetime.combine(datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc)


def usage_today(db: Session, ip: str | None = None) -> int:
    q = db.query(UsageEvent).filter(UsageEvent.created_at >= _start_of_today())
    if ip is not None:
        q = q.filter(UsageEvent.client_ip == ip)
    return q.count()


def remaining_today(db: Session, ip: str) -> dict:
    s = get_settings()
    site = None if s.daily_upload_limit <= 0 else max(0, s.daily_upload_limit - usage_today(db))
    visitor = None if s.per_ip_daily_limit <= 0 else max(0, s.per_ip_daily_limit - usage_today(db, ip))
    return {"site": site, "visitor": visitor}


def consume_ai_run(db: Session, ip: str, kind: str) -> None:
    """Record one AI processing run, or raise 429 when a daily limit is reached."""
    s = get_settings()
    if s.daily_upload_limit > 0 and usage_today(db) >= s.daily_upload_limit:
        raise HTTPException(429, f"The demo has reached today's limit of {s.daily_upload_limit} documents. "
                                 "Please try again tomorrow.")
    if s.per_ip_daily_limit > 0 and usage_today(db, ip) >= s.per_ip_daily_limit:
        raise HTTPException(429, f"You've used your {s.per_ip_daily_limit} documents for today. "
                                 "Please try again tomorrow.")
    db.add(UsageEvent(kind=kind, client_ip=ip))
    db.flush()


class AccessGuard:
    """Bundles the dependencies write endpoints need."""

    def __init__(self, request: Request, _: None = Depends(require_access_code), db: Session = Depends(get_db)):
        self.request = request
        self.db = db
        self.ip = client_ip(request)

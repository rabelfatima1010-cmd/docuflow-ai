"""Load the sample invoices from a real AI run (frontend/public/demo, written by
scripts/export_demo.py) into an empty database, so a fresh deployment isn't blank.

Hosting platforms with temporary disks restart with an empty database; this runs on
every startup and only does anything when there are no documents yet.
"""

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Document, Extraction, ValidationIssue
from app.pipeline.preprocess import sha256_bytes
from app.pipeline.validate import normalize_vendor

log = logging.getLogger(__name__)


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def seed_demo_documents(db: Session) -> int:
    settings = get_settings()
    seed_dir = Path(settings.seed_dir)
    index = seed_dir / "documents.json"
    if not settings.seed_demo or not index.exists() or db.query(Document).count() > 0:
        return 0

    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    # Oldest first so ids come out in the original order
    for summary in sorted(json.loads(index.read_text(encoding="utf-8")), key=lambda d: d["id"]):
        detail_path = seed_dir / "documents" / f"{summary['id']}.json"
        src = next((seed_dir / "files").glob(f"{summary['id']}.*"), None)
        if not detail_path.exists() or src is None:
            continue
        d = json.loads(detail_path.read_text(encoding="utf-8"))
        dest = settings.storage_dir / f"seed-{summary['id']}{src.suffix}"
        shutil.copyfile(src, dest)
        ext = d.get("extraction")
        doc = Document(
            filename=d["filename"],
            source="sample",
            file_path=str(dest),
            file_hash=sha256_bytes(dest.read_bytes()),
            mime_type=d["mime_type"],
            status=d["status"],
            error=d.get("error"),
            auto_approved=d["status"] in ("approved", "exported") and not d.get("issues"),
            vendor_name=d.get("vendor_name"),
            vendor_key=normalize_vendor(d.get("vendor_name")),
            invoice_number=(d.get("approved_data") or (ext or {}).get("data") or {}).get("invoice_number"),
            invoice_date=d.get("invoice_date"),
            total=d.get("total"),
            currency=d.get("currency"),
            category=d.get("category"),
            confidence=d.get("confidence"),
            approved_data=d.get("approved_data"),
            created_at=_dt(d.get("created_at")),
        )
        if ext:
            doc.extractions.append(
                Extraction(
                    version=ext["version"],
                    data=ext.get("data"),
                    confidence=ext["confidence"],
                    model=ext["model"],
                    attempts=ext["attempts"],
                    cost_usd=ext["cost_usd"],
                    latency_ms=ext["latency_ms"],
                    created_at=_dt(ext.get("created_at")),
                )
            )
        for issue in d.get("issues", []):
            doc.issues.append(ValidationIssue(rule=issue["rule"], field=issue.get("field"),
                                              message=issue["message"], severity=issue["severity"]))
        db.add(doc)
        count += 1
    db.commit()
    log.info("Seeded %d sample documents from %s", count, seed_dir)
    return count

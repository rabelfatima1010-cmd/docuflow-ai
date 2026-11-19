import json
import secrets
import uuid
from collections import defaultdict
from pathlib import Path

import pymupdf
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import worker
from app.safeguards import AccessGuard, client_ip, consume_ai_run, remaining_today, require_access_code
from app.config import get_settings
from app.db import get_db
from app.integrations.exporters import export_document, to_csv
from app.models import Correction, DocStatus, Document, Extraction
from app.pipeline.categorize import learn_vendor_category
from app.pipeline.orchestrator import apply_final_data
from app.pipeline.preprocess import SUPPORTED_EXTENSIONS, UnsupportedFileError, mime_for, sha256_bytes
from app.pipeline.validate import normalize_vendor
from app.schemas import (
    CATEGORIES,
    ApproveRequest,
    DocumentDetail,
    DocumentSummary,
    ExtractionOut,
    InvoiceExtraction,
    IssueOut,
    UploadResult,
)

router = APIRouter(prefix="/api")


# ---------- helpers ----------

def _summary(doc: Document) -> DocumentSummary:
    return DocumentSummary(
        id=doc.id,
        filename=doc.filename,
        source=doc.source,
        status=doc.status,
        vendor_name=doc.vendor_name,
        invoice_date=doc.invoice_date,
        total=doc.total,
        currency=doc.currency,
        category=doc.category,
        confidence=doc.confidence,
        error=doc.error,
        created_at=doc.created_at,
    )


def _detail(doc: Document) -> DocumentDetail:
    latest: Extraction | None = doc.extractions[-1] if doc.extractions else None
    return DocumentDetail(
        **_summary(doc).model_dump(),
        mime_type=doc.mime_type,
        extraction=ExtractionOut(
            version=latest.version,
            data=InvoiceExtraction.model_validate(latest.data) if latest.data else None,
            confidence=latest.confidence,
            model=latest.model,
            attempts=latest.attempts,
            cost_usd=latest.cost_usd,
            latency_ms=latest.latency_ms,
            created_at=latest.created_at,
        )
        if latest
        else None,
        approved_data=InvoiceExtraction.model_validate(doc.approved_data) if doc.approved_data else None,
        issues=[
            IssueOut(id=i.id, rule=i.rule, field=i.field, message=i.message, severity=i.severity)
            for i in doc.issues
        ],
    )


def _get_doc(db: Session, doc_id: int) -> Document:
    doc = db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(404, "Document not found")
    return doc


async def _ingest(db: Session, upload: UploadFile, source: str, ip: str | None = None) -> UploadResult:
    """Store an upload and queue it. `ip` set = a public visitor upload, which counts
    against the daily AI limits; None = the owner's own automation (webhooks)."""
    settings = get_settings()
    filename = Path(upload.filename or "upload").name
    try:
        mime = mime_for(filename)
    except UnsupportedFileError as exc:
        return UploadResult(id=None, filename=filename, status="rejected", error=str(exc))

    data = await upload.read()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        return UploadResult(id=None, filename=filename, status="rejected", error=f"File exceeds {settings.max_upload_mb} MB.")
    if not data:
        return UploadResult(id=None, filename=filename, status="rejected", error="File is empty.")
    if mime == "application/pdf" and settings.max_pdf_pages > 0:
        try:
            with pymupdf.open(stream=data, filetype="pdf") as pdf:
                pages = pdf.page_count
        except Exception:
            return UploadResult(id=None, filename=filename, status="rejected", error="Could not open this PDF.")
        if pages > settings.max_pdf_pages:
            return UploadResult(id=None, filename=filename, status="rejected",
                                error=f"PDF has {pages} pages; the limit is {settings.max_pdf_pages}.")

    file_hash = sha256_bytes(data)
    existing = (
        db.query(Document)
        .filter(Document.file_hash == file_hash, Document.status != DocStatus.REJECTED)
        .first()
    )
    if existing:
        return UploadResult(id=existing.id, filename=filename, status="duplicate", duplicate_of=existing.id)

    if ip is not None:
        try:
            consume_ai_run(db, ip, "upload")
        except HTTPException as exc:
            db.rollback()
            return UploadResult(id=None, filename=filename, status="rejected", error=exc.detail)

    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    path = settings.storage_dir / f"{uuid.uuid4().hex}{Path(filename).suffix.lower()}"
    path.write_bytes(data)
    doc = Document(filename=filename, source=source, file_path=str(path), file_hash=file_hash, mime_type=mime)
    db.add(doc)
    db.commit()
    worker.enqueue(doc.id)
    return UploadResult(id=doc.id, filename=filename, status=doc.status)


# ---------- documents ----------

@router.get("/health")
def health(request: Request, db: Session = Depends(get_db)):
    s = get_settings()
    return {"ok": True, "extractor": s.extractor, "model": s.active_model,
            "queue": "redis" if s.redis_url else "in-process",
            "access_code_required": bool(s.upload_access_code),
            "remaining_today": remaining_today(db, client_ip(request)),
            "max_pdf_pages": s.max_pdf_pages}


@router.post("/access-code/check")
def check_access_code(_: None = Depends(require_access_code)):
    return {"ok": True}


@router.get("/categories")
def categories():
    return CATEGORIES


@router.post("/documents", response_model=list[UploadResult])
async def upload_documents(files: list[UploadFile] = File(...), guard: AccessGuard = Depends()):
    return [await _ingest(guard.db, f, "upload", ip=guard.ip) for f in files]


@router.get("/documents", response_model=list[DocumentSummary])
def list_documents(
    status: str | None = None,
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
):
    q = db.query(Document)
    if status:
        q = q.filter(Document.status.in_(status.split(",")))
    return [_summary(d) for d in q.order_by(Document.id.desc()).limit(limit)]


@router.get("/documents/{doc_id}", response_model=DocumentDetail)
def get_document(doc_id: int, db: Session = Depends(get_db)):
    return _detail(_get_doc(db, doc_id))


@router.get("/documents/{doc_id}/file")
def get_document_file(doc_id: int, db: Session = Depends(get_db)):
    doc = _get_doc(db, doc_id)
    return FileResponse(doc.file_path, media_type=doc.mime_type, filename=doc.filename,
                        content_disposition_type="inline")


def _diff(old: dict, new: dict, prefix: str = "") -> list[tuple[str, str | None, str | None]]:
    changes = []
    for key in sorted(set(old) | set(new)):
        if key == "field_confidence":
            continue
        a, b = old.get(key), new.get(key)
        if isinstance(a, dict) and isinstance(b, dict):
            changes += _diff(a, b, f"{prefix}{key}.")
        elif a != b:
            dump = lambda v: None if v is None else (v if isinstance(v, str) else json.dumps(v))  # noqa: E731
            changes.append((f"{prefix}{key}", dump(a), dump(b)))
    return changes


@router.post("/documents/{doc_id}/approve", response_model=DocumentDetail)
def approve_document(doc_id: int, body: ApproveRequest, guard: AccessGuard = Depends()):
    db = guard.db
    doc = _get_doc(db, doc_id)
    if doc.status in (DocStatus.QUEUED, DocStatus.PROCESSING):
        raise HTTPException(409, "Document is still processing")
    new = body.data.model_dump()
    original = doc.extractions[-1].data if doc.extractions else {}
    for field, old_v, new_v in _diff(original or {}, new):
        db.add(Correction(document_id=doc.id, field=field, old_value=old_v, new_value=new_v, reviewer=body.reviewer))

    apply_final_data(doc, body.data, body.data.category)
    learn_vendor_category(db, normalize_vendor(body.data.vendor_name), body.data.vendor_name, body.data.category)
    doc.approved_data, doc.status, doc.auto_approved, doc.error = new, DocStatus.APPROVED, False, None
    db.commit()
    if get_settings().export_on_approve:
        export_document(db, doc)
    return _detail(doc)


@router.post("/documents/{doc_id}/reject", response_model=DocumentDetail)
def reject_document(doc_id: int, guard: AccessGuard = Depends()):
    db = guard.db
    doc = _get_doc(db, doc_id)
    doc.status = DocStatus.REJECTED
    db.commit()
    return _detail(doc)


@router.post("/documents/{doc_id}/reprocess", response_model=DocumentDetail)
def reprocess_document(doc_id: int, guard: AccessGuard = Depends()):
    db = guard.db
    doc = _get_doc(db, doc_id)
    if doc.status == DocStatus.PROCESSING:
        raise HTTPException(409, "Document is already processing")
    consume_ai_run(db, guard.ip, "reprocess")
    doc.status, doc.error, doc.approved_data = DocStatus.QUEUED, None, None
    db.commit()
    worker.enqueue(doc.id)
    return _detail(doc)


@router.post("/documents/{doc_id}/export", response_model=DocumentDetail)
def export_one(doc_id: int, guard: AccessGuard = Depends()):
    db = guard.db
    doc = _get_doc(db, doc_id)
    if doc.status not in DocStatus.DONE:
        raise HTTPException(409, "Only approved documents can be exported")
    if not export_document(db, doc) and not doc.error:
        raise HTTPException(400, "No export target configured (Google Sheets or n8n webhook).")
    return _detail(doc)


@router.get("/export.csv", response_class=PlainTextResponse)
def export_csv(db: Session = Depends(get_db)):
    docs = db.query(Document).filter(Document.status.in_(DocStatus.DONE)).order_by(Document.id).all()
    return PlainTextResponse(
        to_csv(docs), media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="docuflow-export.csv"'},
    )


# ---------- analytics ----------

@router.get("/stats")
def stats(db: Session = Depends(get_db)):
    counts = dict(db.query(Document.status, func.count()).group_by(Document.status).all())
    done = db.query(Document).filter(Document.status.in_(DocStatus.DONE)).all()

    by_month: dict[str, float] = defaultdict(float)
    by_category: dict[str, float] = defaultdict(float)
    by_vendor: dict[str, float] = defaultdict(float)
    currencies: dict[str, int] = defaultdict(int)
    for d in done:
        amount = d.total or 0
        currencies[d.currency or "?"] += 1
        if d.invoice_date:
            by_month[d.invoice_date[:7]] += amount
        by_category[d.category or "Other"] += amount
        by_vendor[d.vendor_name or "Unknown"] += amount

    processed = [d for d in done] + db.query(Document).filter(Document.status == DocStatus.NEEDS_REVIEW).all()
    auto = sum(1 for d in done if d.auto_approved)
    agg = db.query(func.avg(Extraction.cost_usd), func.avg(Extraction.latency_ms), func.sum(Extraction.cost_usd)).one()

    # Simple anomaly flags: an invoice more than 2x the vendor's average of previous invoices
    # (compared within the same currency only)
    anomalies = []
    vendor_hist: dict[tuple[str, str], list[float]] = defaultdict(list)
    for d in sorted(done, key=lambda x: (x.invoice_date or "", x.id)):
        hist = vendor_hist[(d.vendor_key or "", d.currency or "")]
        if len(hist) >= 2 and d.total and d.total > 2 * (sum(hist) / len(hist)):
            anomalies.append({"id": d.id, "vendor": d.vendor_name, "total": d.total,
                              "vendor_avg": round(sum(hist) / len(hist), 2)})
        if d.total:
            hist.append(d.total)

    def top(series: dict[str, float], n: int | None = None):
        items = sorted(series.items(), key=lambda kv: -kv[1])
        return [{"name": k, "total": round(v, 2)} for k, v in (items[:n] if n else items)]

    return {
        "counts": counts,
        "total_documents": sum(counts.values()),
        "approved_total": round(sum(d.total or 0 for d in done), 2),
        "currencies": currencies,
        "auto_approve_rate": round(auto / len(processed), 3) if processed else None,
        "avg_cost_usd": round(agg[0] or 0, 5),
        "total_cost_usd": round(agg[2] or 0, 4),
        "avg_latency_ms": int(agg[1] or 0),
        "spend_by_month": [{"month": k, "total": round(v, 2)} for k, v in sorted(by_month.items())],
        "spend_by_category": top(by_category),
        "top_vendors": top(by_vendor, 8),
        "anomalies": anomalies[-10:],
    }


# ---------- webhooks (n8n intake) ----------

@router.post("/webhooks/ingest", response_model=list[UploadResult])
async def webhook_ingest(
    files: list[UploadFile] = File(...),
    source: str = Form("email"),
    x_webhook_secret: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    expected = get_settings().webhook_secret
    if expected and not (x_webhook_secret and secrets.compare_digest(x_webhook_secret, expected)):
        raise HTTPException(401, "Invalid webhook secret")
    source = source if source in {"email", "drive", "api"} else "api"
    results = []
    for f in files:
        if Path(f.filename or "").suffix.lower() not in SUPPORTED_EXTENSIONS:
            results.append(UploadResult(id=None, filename=f.filename or "", status="skipped",
                                        error="Not a supported document type"))
            continue
        results.append(await _ingest(db, f, source))
    return results

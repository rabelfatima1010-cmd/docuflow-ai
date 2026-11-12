"""Push approved documents to Google Sheets and/or an n8n webhook (e.g. QuickBooks/Xero flows)."""

import csv
import io
import logging

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import DocStatus, Document

log = logging.getLogger(__name__)

CSV_HEADER = [
    "document_id", "vendor", "invoice_number", "invoice_date", "due_date", "currency",
    "subtotal", "tax", "total", "category", "line_items", "source", "auto_approved",
]


def document_row(doc: Document) -> list:
    d = doc.approved_data or {}
    return [
        doc.id,
        d.get("vendor_name"),
        d.get("invoice_number"),
        d.get("invoice_date"),
        d.get("due_date"),
        d.get("currency"),
        d.get("subtotal"),
        d.get("tax"),
        d.get("total"),
        d.get("category"),
        "; ".join(f"{li['description']} = {li['amount']}" for li in d.get("line_items", [])),
        doc.source,
        "yes" if doc.auto_approved else "no",
    ]


def to_csv(docs: list[Document]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_HEADER)
    for doc in docs:
        writer.writerow(document_row(doc))
    return buf.getvalue()


def _export_sheets(doc: Document) -> None:
    settings = get_settings()
    import gspread  # imported lazily: optional integration

    gc = gspread.service_account(filename=settings.google_service_account_file)
    sheet = gc.open_by_key(settings.google_sheet_id)
    try:
        ws = sheet.worksheet(settings.google_worksheet)
    except gspread.WorksheetNotFound:
        ws = sheet.add_worksheet(settings.google_worksheet, rows=1000, cols=len(CSV_HEADER))
        ws.append_row(CSV_HEADER)
    ws.append_row(document_row(doc), value_input_option="USER_ENTERED")


def _export_webhook(doc: Document) -> None:
    settings = get_settings()
    payload = {"document_id": doc.id, "source": doc.source, "auto_approved": doc.auto_approved, **(doc.approved_data or {})}
    httpx.post(settings.n8n_export_webhook_url, json=payload, timeout=15).raise_for_status()


def export_document(db: Session, doc: Document) -> list[str]:
    """Returns the list of targets the document was exported to. Failures are logged and
    stored on the document but do not undo the approval."""
    settings = get_settings()
    done, errors = [], []
    targets = []
    if settings.google_service_account_file and settings.google_sheet_id:
        targets.append(("google_sheets", _export_sheets))
    if settings.n8n_export_webhook_url:
        targets.append(("n8n_webhook", _export_webhook))
    for name, fn in targets:
        try:
            fn(doc)
            done.append(name)
        except Exception as exc:
            log.exception("Export to %s failed for document %s", name, doc.id)
            errors.append(f"{name}: {exc}")
    if done and not errors:
        doc.status = DocStatus.EXPORTED
    doc.error = "Export failed - " + "; ".join(errors) if errors else None
    db.commit()
    return done

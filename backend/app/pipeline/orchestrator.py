"""The agent loop: extract -> validate -> self-correct -> score -> route."""

import logging
from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import DocStatus, Document, Extraction, ValidationIssue
from app.pipeline.categorize import choose_category
from app.pipeline.extract_llm import ExtractionError, ExtractionResult
from app.pipeline.preprocess import PreparedDocument, UnsupportedFileError, prepare
from app.pipeline.validate import confidence_score, normalize_vendor, validate
from app.schemas import InvoiceExtraction, Issue

log = logging.getLogger(__name__)

# Problems the model cannot fix by re-reading the page
NON_CORRECTABLE = {"doc_type", "duplicate"}


class Extractor(Protocol):
    def extract(
        self,
        doc: PreparedDocument,
        previous: InvoiceExtraction | None = None,
        problems: list[str] | None = None,
        force_vision: bool = False,
    ) -> ExtractionResult: ...


@dataclass
class PipelineOutcome:
    data: InvoiceExtraction
    issues: list[Issue]
    confidence: float
    attempts: int
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    trace: list[str] = field(default_factory=list)


def _errors(issues: list[Issue]) -> list[Issue]:
    return [i for i in issues if i.severity == "error" and i.rule not in NON_CORRECTABLE]


def run_extraction(doc: PreparedDocument, extractor: Extractor, max_corrections: int) -> PipelineOutcome:
    """Pure pipeline (no DB). Used by the worker and by the eval harness."""
    result = extractor.extract(doc)
    issues = validate(result.data)
    best = PipelineOutcome(
        data=result.data,
        issues=issues,
        confidence=confidence_score(result.data, issues),
        attempts=1,
        model=result.model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cost_usd=result.cost_usd,
        latency_ms=result.latency_ms,
        trace=[f"attempt 1 ({result.mode}): {len(_errors(issues))} error(s)"],
    )
    totals = [best.input_tokens, best.output_tokens, best.cost_usd, best.latency_ms]
    attempts, mode = 1, result.mode

    while _errors(best.issues) and attempts <= max_corrections:
        attempts += 1
        problems = [i.message for i in _errors(best.issues)]
        # A text-layer pass that failed may have lost table layout: look at the page instead.
        force_vision = mode == "text"
        result = extractor.extract(doc, previous=best.data, problems=problems, force_vision=force_vision)
        mode = result.mode
        totals = [
            totals[0] + result.input_tokens,
            totals[1] + result.output_tokens,
            totals[2] + result.cost_usd,
            totals[3] + result.latency_ms,
        ]
        new_issues = validate(result.data)
        new_conf = confidence_score(result.data, new_issues)
        best.trace.append(f"attempt {attempts} ({mode}): {len(_errors(new_issues))} error(s)")
        if (len(_errors(new_issues)), -new_conf) <= (len(_errors(best.issues)), -best.confidence):
            best.data, best.issues, best.confidence, best.model = result.data, new_issues, new_conf, result.model

    best.attempts = attempts
    best.input_tokens, best.output_tokens = totals[0], totals[1]
    best.cost_usd, best.latency_ms = round(totals[2], 6), totals[3]
    return best


def get_extractor(file_hash: str | None = None) -> Extractor:
    settings = get_settings()
    if settings.extractor == "mock":
        from app.pipeline.extract_mock import MockExtractor

        return MockExtractor(file_hash=file_hash)
    if settings.extractor == "openai":
        from app.pipeline.extract_openai import OpenAIExtractor

        return OpenAIExtractor()
    from app.pipeline.extract_llm import ClaudeExtractor

    return ClaudeExtractor()


def apply_final_data(doc: Document, data: InvoiceExtraction, category: str) -> None:
    doc.vendor_name = data.vendor_name
    doc.vendor_key = normalize_vendor(data.vendor_name)
    doc.invoice_number = data.invoice_number
    doc.invoice_date = data.invoice_date
    doc.total = data.total
    doc.currency = data.currency.upper()[:3]
    doc.category = category


def find_duplicate(db: Session, doc: Document) -> Document | None:
    if not (doc.vendor_key and doc.invoice_number):
        return None
    return (
        db.query(Document)
        .filter(
            Document.id != doc.id,
            Document.vendor_key == doc.vendor_key,
            Document.invoice_number == doc.invoice_number,
            Document.status.notin_([DocStatus.REJECTED, DocStatus.FAILED]),
        )
        .order_by(Document.id)
        .first()
    )


def process_document(db: Session, doc_id: int, extractor: Extractor | None = None) -> Document:
    settings = get_settings()
    doc = db.get(Document, doc_id)
    if doc is None:
        raise ValueError(f"Document {doc_id} not found")
    doc.status, doc.error = DocStatus.PROCESSING, None
    db.commit()

    try:
        prepared = prepare(doc.file_path)
        outcome = run_extraction(prepared, extractor or get_extractor(doc.file_hash), settings.max_correction_attempts)
    except (ExtractionError, UnsupportedFileError) as exc:
        doc.status, doc.error = DocStatus.FAILED, str(exc)
        db.commit()
        return doc
    except Exception as exc:  # keep the worker alive; surface the error in the UI
        log.exception("Processing failed for document %s", doc_id)
        doc.status, doc.error = DocStatus.FAILED, f"Unexpected error: {exc}"
        db.commit()
        return doc

    data = outcome.data
    vendor_key = normalize_vendor(data.vendor_name)
    category = choose_category(db, vendor_key, data)
    data = data.model_copy(update={"category": category})
    apply_final_data(doc, data, category)

    issues = list(outcome.issues)
    dup = find_duplicate(db, doc)
    if dup is not None:
        issues.append(
            Issue(
                rule="duplicate",
                field="invoice_number",
                message=f"Possible duplicate of document #{dup.id} (same vendor and invoice number).",
                severity="error",
            )
        )
        outcome.confidence = min(outcome.confidence, 0.4)

    version = len(doc.extractions) + 1
    db.add(
        Extraction(
            document_id=doc.id,
            version=version,
            data=data.model_dump(),
            confidence=outcome.confidence,
            model=outcome.model,
            attempts=outcome.attempts,
            input_tokens=outcome.input_tokens,
            output_tokens=outcome.output_tokens,
            cost_usd=outcome.cost_usd,
            latency_ms=outcome.latency_ms,
        )
    )
    doc.issues.clear()
    for issue in issues:
        doc.issues.append(ValidationIssue(**issue.model_dump()))
    doc.confidence = outcome.confidence

    has_errors = any(i.severity == "error" for i in issues)
    if not has_errors and outcome.confidence >= settings.auto_approve_threshold:
        doc.status, doc.auto_approved, doc.approved_data = DocStatus.APPROVED, True, data.model_dump()
    else:
        doc.status, doc.auto_approved = DocStatus.NEEDS_REVIEW, False
    db.commit()
    log.info("Document %s -> %s (%s)", doc.id, doc.status, "; ".join(outcome.trace))

    if doc.status == DocStatus.APPROVED and settings.export_on_approve:
        from app.integrations.exporters import export_document

        export_document(db, doc)
    return doc

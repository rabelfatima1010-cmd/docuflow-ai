"""Offline extractor for demos and tests - no API key needed.

Looks for ground truth next to known sample files (samples/ground_truth/<stem>.json, matched by
file hash), otherwise returns a low-confidence placeholder that lands in the review queue."""

import hashlib
import json
from pathlib import Path

from app.pipeline.extract_llm import ExtractionResult
from app.pipeline.preprocess import PreparedDocument
from app.schemas import InvoiceExtraction

REPO_ROOT = Path(__file__).resolve().parents[3]
SAMPLES_DIR = REPO_ROOT / "samples"


def _ground_truth_index() -> dict[str, Path]:
    index: dict[str, Path] = {}
    gt_dir = SAMPLES_DIR / "ground_truth"
    if not gt_dir.exists():
        return index
    for doc in SAMPLES_DIR.glob("invoices/*"):
        gt = gt_dir / f"{doc.stem}.json"
        if gt.exists():
            index[hashlib.sha256(doc.read_bytes()).hexdigest()] = gt
    return index


PLACEHOLDER = {
    "doc_type": "invoice",
    "vendor_name": "Unknown vendor",
    "vendor_tax_id": None,
    "invoice_number": None,
    "invoice_date": None,
    "due_date": None,
    "currency": "USD",
    "subtotal": None,
    "tax": None,
    "total": 0.01,
    "line_items": [],
    "category": "Other",
    "field_confidence": {"vendor_name": 0.1, "invoice_number": 0.1, "invoice_date": 0.1, "total": 0.1, "line_items": 0.1},
}


class MockExtractor:
    model = "mock"

    def __init__(self, file_hash: str | None = None):
        self.file_hash = file_hash
        self._index = _ground_truth_index()

    def extract(self, doc: PreparedDocument, previous=None, problems=None, force_vision=False) -> ExtractionResult:
        gt_path = self._index.get(self.file_hash or "")
        raw = json.loads(gt_path.read_text()) if gt_path else PLACEHOLDER
        return ExtractionResult(
            data=InvoiceExtraction.model_validate(raw),
            model=self.model,
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            latency_ms=5,
            mode="mock",
        )

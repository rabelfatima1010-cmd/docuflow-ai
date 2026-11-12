"""Pydantic schemas. `InvoiceExtraction` is also the structured-output schema sent to the LLM,
so every field is required (nullable where the value may be missing on the document)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

CATEGORIES = [
    "Software & SaaS",
    "Office Supplies",
    "Travel",
    "Meals & Entertainment",
    "Utilities",
    "Rent & Facilities",
    "Professional Services",
    "Marketing & Advertising",
    "Shipping & Logistics",
    "Hardware & Equipment",
    "Inventory & Materials",
    "Other",
]

Category = Literal[
    "Software & SaaS",
    "Office Supplies",
    "Travel",
    "Meals & Entertainment",
    "Utilities",
    "Rent & Facilities",
    "Professional Services",
    "Marketing & Advertising",
    "Shipping & Logistics",
    "Hardware & Equipment",
    "Inventory & Materials",
    "Other",
]


class LineItem(BaseModel):
    description: str
    quantity: float | None
    unit_price: float | None
    amount: float


class FieldConfidence(BaseModel):
    """Model's own 0-1 confidence for the key fields."""

    vendor_name: float
    invoice_number: float
    invoice_date: float
    total: float
    line_items: float


class InvoiceExtraction(BaseModel):
    doc_type: Literal["invoice", "receipt", "other"]
    vendor_name: str
    vendor_tax_id: str | None
    invoice_number: str | None
    invoice_date: str | None = Field(description="ISO date YYYY-MM-DD")
    due_date: str | None = Field(description="ISO date YYYY-MM-DD")
    currency: str = Field(description="ISO 4217 code, e.g. USD, EUR, PKR")
    subtotal: float | None
    tax: float | None
    total: float
    line_items: list[LineItem]
    category: Category
    field_confidence: FieldConfidence


class Issue(BaseModel):
    rule: str
    field: str | None = None
    message: str
    severity: Literal["error", "warning"]


class IssueOut(Issue):
    id: int


class ExtractionOut(BaseModel):
    version: int
    data: InvoiceExtraction | None
    confidence: float
    model: str
    attempts: int
    cost_usd: float
    latency_ms: int
    created_at: datetime


class DocumentSummary(BaseModel):
    id: int
    filename: str
    source: str
    status: str
    vendor_name: str | None
    invoice_date: str | None
    total: float | None
    currency: str | None
    category: str | None
    confidence: float | None
    error: str | None
    created_at: datetime


class DocumentDetail(DocumentSummary):
    mime_type: str
    extraction: ExtractionOut | None
    approved_data: InvoiceExtraction | None
    issues: list[IssueOut]


class ApproveRequest(BaseModel):
    data: InvoiceExtraction
    reviewer: str = "reviewer"


class UploadResult(BaseModel):
    id: int | None
    filename: str
    status: str
    duplicate_of: int | None = None
    error: str | None = None

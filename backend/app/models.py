from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DocStatus:
    QUEUED = "queued"
    PROCESSING = "processing"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    EXPORTED = "exported"
    REJECTED = "rejected"
    FAILED = "failed"

    DONE = (APPROVED, EXPORTED)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(32), default="upload")  # upload | email | drive | api
    file_path: Mapped[str] = mapped_column(String(512))
    file_hash: Mapped[str] = mapped_column(String(64), index=True)
    mime_type: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default=DocStatus.QUEUED, index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    auto_approved: Mapped[bool] = mapped_column(Boolean, default=False)

    # Denormalised from the final (approved or latest) data for fast listing/analytics
    vendor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    vendor_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    invoice_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    invoice_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    total: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    approved_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    extractions: Mapped[list["Extraction"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="Extraction.version"
    )
    issues: Mapped[list["ValidationIssue"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class Extraction(Base):
    __tablename__ = "extractions"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    model: Mapped[str] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    document: Mapped[Document] = relationship(back_populates="extractions")


class ValidationIssue(Base):
    __tablename__ = "validation_issues"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    rule: Mapped[str] = mapped_column(String(64))
    field: Mapped[str | None] = mapped_column(String(64), nullable=True)
    message: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(16))

    document: Mapped[Document] = relationship(back_populates="issues")


class Vendor(Base):
    """Learned per-vendor defaults (category), updated from reviewer corrections."""

    __tablename__ = "vendors"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(255), unique=True)
    display_name: Mapped[str] = mapped_column(String(255))
    default_category: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Correction(Base):
    __tablename__ = "corrections"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    field: Mapped[str] = mapped_column(String(64))
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

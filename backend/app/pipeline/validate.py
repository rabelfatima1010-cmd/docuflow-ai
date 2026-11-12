"""Deterministic checks on an extraction. Errors trigger self-correction and review."""

import re
from datetime import date, timedelta

from app.schemas import InvoiceExtraction, Issue

ISO_CURRENCIES = {
    "USD", "EUR", "GBP", "PKR", "INR", "AED", "SAR", "CAD", "AUD", "NZD", "JPY", "CNY", "CHF",
    "SEK", "NOK", "DKK", "SGD", "HKD", "MYR", "ZAR", "BRL", "MXN", "TRY", "QAR", "KWD", "BDT",
}


def money_tolerance(amount: float) -> float:
    return max(0.02, abs(amount) * 0.005)


def normalize_vendor(name: str | None) -> str | None:
    if not name:
        return None
    key = name.lower()
    key = re.sub(r"[^a-z0-9 ]", " ", key)
    key = re.sub(r"\b(inc|llc|ltd|limited|corp|corporation|co|gmbh|plc|pvt|private|company)\b", " ", key)
    key = re.sub(r"\s+", " ", key).strip()
    return key or None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def validate(data: InvoiceExtraction, today: date | None = None) -> list[Issue]:
    today = today or date.today()
    issues: list[Issue] = []

    def add(rule: str, field: str | None, message: str, severity: str = "error") -> None:
        issues.append(Issue(rule=rule, field=field, message=message, severity=severity))

    if data.doc_type == "other":
        add("doc_type", "doc_type", "Document does not look like an invoice or receipt.")

    if not data.vendor_name.strip():
        add("vendor_required", "vendor_name", "Vendor name is missing.")

    if data.total <= 0:
        add("total_positive", "total", f"Total must be positive (got {data.total}).")

    # Line items should add up to the subtotal (or to the total when there is no subtotal/tax)
    if data.line_items:
        items_sum = round(sum(li.amount for li in data.line_items), 2)
        target_name, target = ("subtotal", data.subtotal) if data.subtotal is not None else (None, None)
        if target is None and data.tax in (None, 0):
            target_name, target = "total", data.total
        if target is not None and abs(items_sum - target) > money_tolerance(target):
            add(
                "line_items_sum",
                "line_items",
                f"Line items sum to {items_sum:.2f} but {target_name} is {target:.2f}.",
            )
        for i, li in enumerate(data.line_items):
            if li.quantity is not None and li.unit_price is not None:
                expected = round(li.quantity * li.unit_price, 2)
                if abs(expected - li.amount) > money_tolerance(li.amount):
                    add(
                        "line_item_math",
                        "line_items",
                        f"Line {i + 1} ('{li.description[:40]}'): {li.quantity} x {li.unit_price} = "
                        f"{expected:.2f}, but amount is {li.amount:.2f}.",
                        "warning",
                    )
    elif data.doc_type == "invoice":
        add("line_items_missing", "line_items", "No line items extracted.", "warning")

    if data.subtotal is not None:
        expected_total = round(data.subtotal + (data.tax or 0), 2)
        if abs(expected_total - data.total) > money_tolerance(data.total):
            add(
                "totals_math",
                "total",
                f"Subtotal {data.subtotal:.2f} + tax {data.tax or 0:.2f} = {expected_total:.2f}, "
                f"but total is {data.total:.2f}.",
            )

    inv_date = _parse_date(data.invoice_date)
    if data.invoice_date and inv_date is None:
        add("date_format", "invoice_date", f"Invoice date '{data.invoice_date}' is not YYYY-MM-DD.")
    elif inv_date is None:
        add("date_missing", "invoice_date", "Invoice date is missing.", "warning")
    else:
        if inv_date > today + timedelta(days=1):
            add("date_future", "invoice_date", f"Invoice date {inv_date} is in the future.")
        elif inv_date < today - timedelta(days=365 * 5):
            add("date_old", "invoice_date", f"Invoice date {inv_date} is more than 5 years old.", "warning")

    due = _parse_date(data.due_date)
    if data.due_date and due is None:
        add("date_format", "due_date", f"Due date '{data.due_date}' is not YYYY-MM-DD.")
    elif due and inv_date and due < inv_date:
        add("due_before_issue", "due_date", f"Due date {due} is before invoice date {inv_date}.")

    if data.currency.upper() not in ISO_CURRENCIES:
        add("currency", "currency", f"Unrecognised currency code '{data.currency}'.", "warning")

    if data.doc_type == "invoice" and not data.invoice_number:
        add("invoice_number_missing", "invoice_number", "Invoice number is missing.", "warning")

    return issues


def amounts_cross_check(data: InvoiceExtraction) -> bool:
    """True when the money fields independently confirm each other: line items add up to the
    subtotal AND subtotal + tax equals the total. Three numbers agreeing by accident is very
    unlikely, so this is stronger evidence than the model's own confidence."""
    if not data.line_items or data.subtotal is None:
        return False
    items_sum = sum(li.amount for li in data.line_items)
    expected_total = data.subtotal + (data.tax or 0)
    return (
        abs(items_sum - data.subtotal) <= money_tolerance(data.subtotal)
        and abs(expected_total - data.total) <= money_tolerance(data.total)
    )


VERIFIED_AMOUNT_CONFIDENCE = 0.95


def confidence_score(data: InvoiceExtraction, issues: list[Issue]) -> float:
    """Combine the model's self-reported confidence with validation results.

    Self-reported confidence alone is unreliable, so validation dominates:
    any error caps the score at 0.4; each warning costs 0.1. When the amounts
    cross-check exactly, total and line-item confidence are raised to 0.95.
    """
    fc = data.field_confidence
    total_conf, items_conf = fc.total, fc.line_items
    if amounts_cross_check(data):
        total_conf = max(total_conf, VERIFIED_AMOUNT_CONFIDENCE)
        items_conf = max(items_conf, VERIFIED_AMOUNT_CONFIDENCE)
    score = min(fc.vendor_name, total_conf, fc.invoice_date, items_conf)
    if data.doc_type == "invoice":
        score = min(score, fc.invoice_number)
    score = max(0.0, min(1.0, score))
    if any(i.severity == "error" for i in issues):
        score = min(score, 0.4)
    score -= 0.1 * sum(1 for i in issues if i.severity == "warning")
    return round(max(0.0, score), 3)

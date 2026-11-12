from datetime import date

from app.pipeline.validate import confidence_score, normalize_vendor, validate
from tests.factories import invoice

TODAY = date(2026, 11, 12)


def rules(data):
    return {i.rule for i in validate(data, today=TODAY)}


def test_clean_invoice_has_no_issues():
    data = invoice()
    assert validate(data, today=TODAY) == []
    assert confidence_score(data, []) == 0.96


def test_line_items_must_sum_to_subtotal():
    data = invoice(subtotal=160.0, total=176.0, tax=16.0)
    assert "line_items_sum" in rules(data)


def test_totals_math():
    assert "totals_math" in rules(invoice(total=170.0))


def test_line_items_compared_to_total_when_no_subtotal_or_tax():
    assert rules(invoice(subtotal=None, tax=None, total=150.0)) == set()
    assert "line_items_sum" in rules(invoice(subtotal=None, tax=None, total=149.0))


def test_dates():
    assert "date_future" in rules(invoice(invoice_date="2027-06-01", due_date=None))
    assert "due_before_issue" in rules(invoice(due_date="2026-02-01"))
    assert "date_format" in rules(invoice(invoice_date="03/01/2026"))


def test_line_item_math_is_a_warning():
    data = invoice(line_items=[
        {"description": "Cloud server", "quantity": 2, "unit_price": 40.0, "amount": 100.0},
        {"description": "Backup storage", "quantity": 1, "unit_price": 50.0, "amount": 50.0},
    ])
    issues = validate(data, today=TODAY)
    assert [(i.rule, i.severity) for i in issues] == [("line_item_math", "warning")]
    assert confidence_score(data, issues) < 0.9


def test_cross_checked_amounts_raise_confidence():
    hesitant = {"vendor_name": 0.99, "invoice_number": 0.99, "invoice_date": 0.99, "total": 0.65, "line_items": 0.7}
    data = invoice(field_confidence=hesitant)
    assert confidence_score(data, []) == 0.95  # amounts agree -> trusted
    # No subtotal to cross-check against -> the model's own doubt stands
    unverifiable = invoice(field_confidence=hesitant, subtotal=None, tax=None, total=150.0)
    assert confidence_score(unverifiable, []) == 0.65
    # Doubt about non-numeric fields is never overridden
    blurry = invoice(field_confidence={**hesitant, "vendor_name": 0.69})
    assert confidence_score(blurry, []) == 0.69


def test_errors_cap_confidence():
    data = invoice(total=999.0)
    issues = validate(data, today=TODAY)
    assert confidence_score(data, issues) <= 0.4


def test_normalize_vendor():
    assert normalize_vendor("CloudNest Hosting, LLC.") == "cloudnest hosting"
    assert normalize_vendor("cloudnest hosting llc") == "cloudnest hosting"
    assert normalize_vendor("") is None

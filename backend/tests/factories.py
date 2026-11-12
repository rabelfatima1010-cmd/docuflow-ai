from app.schemas import InvoiceExtraction


def invoice(**overrides) -> InvoiceExtraction:
    data = {
        "doc_type": "invoice",
        "vendor_name": "CloudNest Hosting LLC",
        "vendor_tax_id": None,
        "invoice_number": "INV-2026-1001",
        "invoice_date": "2026-03-01",
        "due_date": "2026-03-31",
        "currency": "USD",
        "subtotal": 150.0,
        "tax": 15.0,
        "total": 165.0,
        "line_items": [
            {"description": "Cloud server", "quantity": 2, "unit_price": 50.0, "amount": 100.0},
            {"description": "Backup storage", "quantity": 1, "unit_price": 50.0, "amount": 50.0},
        ],
        "category": "Software & SaaS",
        "field_confidence": {"vendor_name": 0.99, "invoice_number": 0.98, "invoice_date": 0.97,
                             "total": 0.99, "line_items": 0.96},
    }
    data.update(overrides)
    return InvoiceExtraction.model_validate(data)

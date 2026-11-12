"""End-to-end API flow with the offline mock extractor and synchronous processing."""

import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import worker
from app.main import app
from app.pipeline import extract_mock


@pytest.fixture()
def client(monkeypatch, tmp_path):
    # Process synchronously so tests are deterministic
    monkeypatch.setattr(worker, "enqueue", worker.process_job)
    with TestClient(app) as c:
        yield c


def png_bytes(color=(255, 255, 255), size=(400, 300)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def register_ground_truth(monkeypatch, data: bytes, gt: dict, tmp_path):
    import hashlib

    path = tmp_path / f"gt_{hashlib.sha256(data).hexdigest()[:8]}.json"
    path.write_text(json.dumps(gt))
    original = extract_mock._ground_truth_index

    def index():
        idx = original()
        idx[hashlib.sha256(data).hexdigest()] = path
        return idx

    monkeypatch.setattr(extract_mock, "_ground_truth_index", index)


GOOD = {
    "doc_type": "invoice", "vendor_name": "Pixel Hardware Co", "vendor_tax_id": None,
    "invoice_number": "INV-1", "invoice_date": "2026-05-02", "due_date": "2026-06-01", "currency": "USD",
    "subtotal": 200.0, "tax": 20.0, "total": 220.0,
    "line_items": [{"description": "Monitor", "quantity": 1, "unit_price": 200.0, "amount": 200.0}],
    "category": "Hardware & Equipment",
    "field_confidence": {"vendor_name": 0.99, "invoice_number": 0.99, "invoice_date": 0.99, "total": 0.99, "line_items": 0.99},
}


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["extractor"] == "mock"


def test_clean_document_is_auto_approved(client, monkeypatch, tmp_path):
    data = png_bytes((250, 250, 250))
    register_ground_truth(monkeypatch, data, GOOD, tmp_path)
    r = client.post("/api/documents", files=[("files", ("inv.png", data, "image/png"))])
    assert r.status_code == 200
    doc_id = r.json()[0]["id"]
    detail = client.get(f"/api/documents/{doc_id}").json()
    assert detail["status"] == "approved"
    assert detail["total"] == 220.0
    assert detail["approved_data"]["vendor_name"] == "Pixel Hardware Co"

    # Same file again -> duplicate, not reprocessed
    r = client.post("/api/documents", files=[("files", ("again.png", data, "image/png"))])
    assert r.json()[0]["status"] == "duplicate" and r.json()[0]["duplicate_of"] == doc_id

    csv_text = client.get("/api/export.csv").text
    assert "Pixel Hardware Co" in csv_text


def test_bad_document_goes_to_review_and_learns_from_correction(client, monkeypatch, tmp_path):
    data = png_bytes((240, 240, 240))
    bad = {**GOOD, "invoice_number": "INV-2", "total": 999.0}
    register_ground_truth(monkeypatch, data, bad, tmp_path)
    doc_id = client.post("/api/documents", files=[("files", ("bad.png", data, "image/png"))]).json()[0]["id"]

    detail = client.get(f"/api/documents/{doc_id}").json()
    assert detail["status"] == "needs_review"
    assert any(i["rule"] == "totals_math" for i in detail["issues"])
    assert detail["extraction"]["attempts"] == 3  # 1 + 2 corrections (mock keeps returning the same)

    fixed = {**bad, "total": 220.0, "category": "Office Supplies"}
    r = client.post(f"/api/documents/{doc_id}/approve", json={"data": fixed})
    assert r.status_code == 200 and r.json()["status"] == "approved"

    # Vendor category was learned from the correction
    data2 = png_bytes((230, 230, 230))
    register_ground_truth(monkeypatch, data2, {**GOOD, "invoice_number": "INV-3"}, tmp_path)
    doc2 = client.post("/api/documents", files=[("files", ("next.png", data2, "image/png"))]).json()[0]["id"]
    assert client.get(f"/api/documents/{doc2}").json()["category"] == "Office Supplies"


def test_duplicate_invoice_number_flagged(client, monkeypatch, tmp_path):
    a, b = png_bytes((200, 200, 200)), png_bytes((201, 201, 201))
    gt = {**GOOD, "vendor_name": "SwiftShip Couriers", "invoice_number": "DUP-9"}
    register_ground_truth(monkeypatch, a, gt, tmp_path)
    register_ground_truth(monkeypatch, b, gt, tmp_path)
    client.post("/api/documents", files=[("files", ("a.png", a, "image/png"))])
    second = client.post("/api/documents", files=[("files", ("b.png", b, "image/png"))]).json()[0]["id"]
    detail = client.get(f"/api/documents/{second}").json()
    assert detail["status"] == "needs_review"
    assert any(i["rule"] == "duplicate" for i in detail["issues"])


def test_unsupported_file_rejected(client):
    r = client.post("/api/documents", files=[("files", ("notes.txt", b"hello", "text/plain"))])
    assert r.json()[0]["status"] == "rejected"


def test_webhook_requires_secret(client, monkeypatch, tmp_path):
    data = png_bytes((210, 210, 210))
    files = [("files", ("mail.png", data, "image/png"))]
    assert client.post("/api/webhooks/ingest", files=files, data={"source": "email"}).status_code == 401
    r = client.post("/api/webhooks/ingest", files=files, data={"source": "email"},
                    headers={"X-Webhook-Secret": "test-secret"})
    assert r.status_code == 200
    doc_id = r.json()[0]["id"]
    assert client.get(f"/api/documents/{doc_id}").json()["source"] == "email"


def test_stats(client):
    s = client.get("/api/stats").json()
    assert "spend_by_month" in s and "auto_approve_rate" in s

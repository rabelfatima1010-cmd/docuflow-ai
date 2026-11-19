"""Access code, daily AI limits, PDF page cap and demo seeding."""

import io

import pymupdf
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import worker
from app.config import get_settings
from app.db import SessionLocal
from app.main import app
from app.models import Document, UsageEvent
from app.seed import seed_demo_documents


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(worker, "enqueue", worker.process_job)
    db = SessionLocal()
    db.query(UsageEvent).delete()
    db.commit()
    db.close()
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def settings(monkeypatch):
    s = get_settings()
    return lambda **kw: [monkeypatch.setattr(s, k, v) for k, v in kw.items()]


_shade = iter(range(10, 250))


def png() -> bytes:
    buf = io.BytesIO()
    v = next(_shade)
    Image.new("RGB", (300, 200), (v, 120, 255 - v)).save(buf, format="PNG")
    return buf.getvalue()


def upload(client, headers=None, data=None, name="inv.png"):
    return client.post("/api/documents", files=[("files", (name, data or png(), "image/png"))], headers=headers or {})


def test_access_code_required_for_writes_only(client, settings):
    settings(upload_access_code="letmein")
    assert client.get("/api/health").json()["access_code_required"] is True
    assert client.get("/api/documents").status_code == 200  # browsing stays open
    assert upload(client).status_code == 401
    assert upload(client, {"X-Access-Code": "wrong"}).status_code == 403
    assert client.post("/api/access-code/check", headers={"X-Access-Code": "wrong"}).status_code == 403
    assert client.post("/api/access-code/check", headers={"X-Access-Code": "letmein"}).status_code == 200
    r = upload(client, {"X-Access-Code": "letmein"})
    assert r.status_code == 200 and r.json()[0]["id"]
    doc_id = r.json()[0]["id"]
    assert client.post(f"/api/documents/{doc_id}/reject").status_code == 401
    assert client.post(f"/api/documents/{doc_id}/reject", headers={"X-Access-Code": "letmein"}).status_code == 200


def test_per_visitor_daily_limit(client, settings):
    settings(per_ip_daily_limit=2, daily_upload_limit=0)
    assert upload(client).json()[0]["status"] != "rejected"
    assert upload(client).json()[0]["status"] != "rejected"
    third = upload(client).json()[0]
    assert third["status"] == "rejected" and "your 2 documents" in third["error"]
    # A different visitor still has their own allowance
    other = upload(client, {"X-Forwarded-For": "203.0.113.9"}).json()[0]
    assert other["status"] != "rejected"
    assert client.get("/api/health").json()["remaining_today"]["visitor"] == 0


def test_site_wide_daily_limit_and_reprocess_counts(client, settings):
    settings(per_ip_daily_limit=0, daily_upload_limit=2)
    doc_id = upload(client).json()[0]["id"]
    assert client.post(f"/api/documents/{doc_id}/reprocess").status_code == 200  # 2nd AI run
    assert client.post(f"/api/documents/{doc_id}/reprocess").status_code == 429
    assert upload(client).json()[0]["status"] == "rejected"


def test_duplicates_and_bad_files_do_not_use_allowance(client, settings):
    settings(per_ip_daily_limit=1, daily_upload_limit=0)
    data = png()
    upload(client, data=data)
    assert upload(client, data=data).json()[0]["status"] == "duplicate"
    assert client.post("/api/documents", files=[("files", ("x.txt", b"hi", "text/plain"))]).json()[0]["status"] == "rejected"
    db = SessionLocal()
    assert db.query(UsageEvent).count() == 1
    db.close()


def test_pdf_page_limit(client, settings):
    settings(max_pdf_pages=2)
    pdf = pymupdf.open()
    for _ in range(3):
        pdf.new_page()
    r = client.post("/api/documents", files=[("files", ("long.pdf", pdf.tobytes(), "application/pdf"))]).json()[0]
    assert r["status"] == "rejected" and "3 pages" in r["error"]


def test_seed_loads_sample_run_into_empty_db(settings, tmp_path):
    from pathlib import Path

    seed_dir = Path(__file__).resolve().parents[2] / "frontend" / "public" / "demo"
    if not (seed_dir / "documents.json").exists():
        pytest.skip("no demo snapshot")
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db import Base

    engine = create_engine(f"sqlite:///{(tmp_path / 'seed.db').as_posix()}")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    settings(seed_demo=True, seed_dir=seed_dir, storage_dir=tmp_path / "files")
    n = seed_demo_documents(db)
    assert n == 20 and db.query(Document).count() == 20
    flagged = db.query(Document).filter_by(status="needs_review").all()
    assert len(flagged) == 3 and all(d.issues or d.confidence < 0.9 for d in flagged)
    assert all(Path(d.file_path).exists() for d in db.query(Document))
    assert seed_demo_documents(db) == 0  # never seeds twice
    db.close()

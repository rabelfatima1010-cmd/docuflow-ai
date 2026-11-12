"""ClaudeExtractor request shape, checked with a fake client (no network)."""

from types import SimpleNamespace

import pytest

from app.pipeline.extract_llm import ClaudeExtractor, ExtractionError
from app.pipeline.preprocess import PreparedDocument, prepare_image, prepare_pdf
from app.schemas import InvoiceExtraction
from tests.factories import invoice


class FakeClient:
    def __init__(self, stop_reason="end_turn"):
        self.kwargs = None
        self.stop_reason = stop_reason
        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=self.parse))

    def parse(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            parsed_output=invoice(),
            content=[],
            model="claude-opus-5-5",
            usage=SimpleNamespace(input_tokens=2000, output_tokens=500),
        )


def test_request_shape_for_image():
    client = FakeClient()
    doc = PreparedDocument(kind="image", media_type="image/png", b64="QQ==")
    result = ClaudeExtractor(client=client).extract(doc)
    kw = client.kwargs
    assert kw["model"] == "claude-opus-5-5"
    assert kw["output_format"] is InvoiceExtraction
    assert kw["output_config"] == {"effort": "medium"}
    assert kw["fallbacks"] == "default" and kw["betas"] == ["server-side-fallback-2026-07-01"]
    content = kw["messages"][0]["content"]
    assert content[0]["type"] == "image" and content[-1]["type"] == "text"
    assert result.cost_usd == pytest.approx(0.018)
    assert result.mode == "vision"


def test_correction_prompt_included():
    client = FakeClient()
    doc = PreparedDocument(kind="image", media_type="image/png", b64="QQ==")
    ClaudeExtractor(client=client).extract(doc, previous=invoice(total=1.0), problems=["Total mismatch"])
    text = client.kwargs["messages"][0]["content"][-1]["text"]
    assert "Total mismatch" in text and '"total": 1.0' in text


def test_refusal_raises():
    doc = PreparedDocument(kind="image", media_type="image/png", b64="QQ==")
    with pytest.raises(ExtractionError):
        ClaudeExtractor(client=FakeClient(stop_reason="refusal")).extract(doc)


def test_prepare_image_and_pdf():
    import io

    import pymupdf
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (3000, 1000), "white").save(buf, format="PNG")
    prepared = prepare_image(buf.getvalue())
    assert prepared.media_type == "image/png" and any("resized" in n for n in prepared.notes)

    pdf = pymupdf.open()
    page = pdf.new_page()
    for i in range(12):
        page.insert_text((72, 72 + i * 20), f"INVOICE Acme Ltd line {i} total 100.00")
    pdf_doc = prepare_pdf(pdf.tobytes())
    assert pdf_doc.kind == "pdf" and pdf_doc.text and "Acme" in pdf_doc.text

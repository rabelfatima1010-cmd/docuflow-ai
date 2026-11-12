"""OpenAIExtractor request shape, checked with a fake client (no network)."""

from types import SimpleNamespace

import pytest

from app.pipeline.extract_llm import ExtractionError
from app.pipeline.extract_openai import OpenAIExtractor, build_openai_content
from app.pipeline.orchestrator import run_extraction
from app.pipeline.preprocess import PreparedDocument
from app.schemas import InvoiceExtraction
from tests.factories import invoice


class FakeOpenAI:
    def __init__(self, outputs=None, refusal=None):
        self.calls = []
        self.outputs = list(outputs or [invoice()])
        self.refusal = refusal
        self.chat = SimpleNamespace(completions=SimpleNamespace(parse=self.parse))

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        parsed = None if self.refusal else self.outputs.pop(0)
        message = SimpleNamespace(parsed=parsed, refusal=self.refusal)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage=SimpleNamespace(prompt_tokens=3000, completion_tokens=600),
        )


IMG = PreparedDocument(kind="image", media_type="image/png", b64="QQ==")


def test_request_shape_for_image():
    client = FakeOpenAI()
    result = OpenAIExtractor(client=client, model="gpt-6.1-sol").extract(IMG)
    kw = client.calls[0]
    assert kw["model"] == "gpt-6.1-sol"
    assert kw["response_format"] is InvoiceExtraction
    assert kw["messages"][0]["role"] == "system"
    parts = kw["messages"][1]["content"]
    assert parts[0]["type"] == "image_url"
    assert parts[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert parts[-1]["type"] == "text"
    assert "reasoning_effort" not in kw
    assert result.cost_usd == pytest.approx(0.012)  # 3000 x $2/M + 600 x $10/M
    assert result.mode == "vision"


def test_pdf_and_text_modes():
    pdf = PreparedDocument(kind="pdf", media_type="application/pdf", b64="QQ==", text="Invoice " * 50)
    parts, mode = build_openai_content(pdf, use_text_mode=False)
    assert mode == "vision" and parts[0]["type"] == "file"
    assert parts[0]["file"]["file_data"].startswith("data:application/pdf;base64,")
    parts, mode = build_openai_content(pdf, use_text_mode=True)
    assert mode == "text" and parts[0]["type"] == "text"


def test_refusal_raises():
    with pytest.raises(ExtractionError):
        OpenAIExtractor(client=FakeOpenAI(refusal="I can't help with that")).extract(IMG)


def test_schema_is_valid_for_openai_strict_mode():
    from openai.lib._parsing._completions import type_to_response_format_param

    fmt = type_to_response_format_param(InvoiceExtraction)
    schema = fmt["json_schema"]["schema"]
    assert fmt["json_schema"]["strict"] is True
    assert set(schema["required"]) == set(schema["properties"])


def test_missing_key_raises(monkeypatch):
    from app.config import get_settings

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(get_settings(), "openai_api_key", None)
    with pytest.raises(ExtractionError, match="OPENAI_API_KEY"):
        OpenAIExtractor()


def test_self_correction_loop_works_with_openai():
    client = FakeOpenAI(outputs=[invoice(total=175.0), invoice()])
    out = run_extraction(IMG, OpenAIExtractor(client=client), max_corrections=2)
    assert out.attempts == 2 and out.issues == []
    assert "total is 175.00" in client.calls[1]["messages"][1]["content"][-1]["text"]

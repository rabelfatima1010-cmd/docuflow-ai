"""Self-correction loop with a scripted fake extractor."""

from app.pipeline.extract_llm import ExtractionResult, build_content, estimate_cost
from app.pipeline.orchestrator import run_extraction
from app.pipeline.preprocess import PreparedDocument
from tests.factories import invoice


class ScriptedExtractor:
    def __init__(self, outputs, mode="vision"):
        self.outputs = list(outputs)
        self.calls = []
        self.mode = mode

    def extract(self, doc, previous=None, problems=None, force_vision=False):
        self.calls.append({"previous": previous, "problems": problems, "force_vision": force_vision})
        data = self.outputs.pop(0)
        return ExtractionResult(data=data, model="fake", input_tokens=1000, output_tokens=200,
                                cost_usd=0.01, latency_ms=100, mode="vision" if force_vision else self.mode)


DOC = PreparedDocument(kind="image", media_type="image/png", b64="")


def test_clean_first_pass_needs_one_call():
    ex = ScriptedExtractor([invoice()])
    out = run_extraction(DOC, ex, max_corrections=2)
    assert out.attempts == 1 and len(ex.calls) == 1
    assert out.issues == []


def test_self_correction_fixes_math_error():
    bad = invoice(total=175.0)  # misread total
    ex = ScriptedExtractor([bad, invoice()])
    out = run_extraction(DOC, ex, max_corrections=2)
    assert out.attempts == 2
    assert out.data.total == 165.0
    assert out.issues == []
    assert ex.calls[1]["previous"] == bad
    assert any("total is 175.00" in p for p in ex.calls[1]["problems"])
    assert out.cost_usd == 0.02 and out.input_tokens == 2000


def test_gives_up_after_max_corrections_and_keeps_best():
    ex = ScriptedExtractor([invoice(total=175.0), invoice(total=999.0), invoice(total=180.0)])
    out = run_extraction(DOC, ex, max_corrections=2)
    assert out.attempts == 3
    assert any(i.severity == "error" for i in out.issues)
    assert out.confidence <= 0.4


def test_text_mode_failure_retries_with_vision():
    ex = ScriptedExtractor([invoice(total=175.0), invoice()], mode="text")
    run_extraction(DOC, ex, max_corrections=1)
    assert ex.calls[1]["force_vision"] is True


def test_build_content_modes():
    pdf = PreparedDocument(kind="pdf", media_type="application/pdf", b64="QQ==", text="Invoice text " * 30)
    blocks, mode = build_content(pdf, use_text_mode=True)
    assert mode == "text" and blocks[0]["type"] == "text"
    blocks, mode = build_content(pdf, use_text_mode=False)
    assert mode == "vision" and blocks[0]["type"] == "document"
    img = PreparedDocument(kind="image", media_type="image/png", b64="QQ==")
    assert build_content(img, use_text_mode=True)[0][0]["type"] == "image"


def test_cost_estimate():
    assert estimate_cost("claude-opus-5-5", 1_000_000, 100_000) == 6.0
    assert estimate_cost("unknown", 10, 10) == 0.0

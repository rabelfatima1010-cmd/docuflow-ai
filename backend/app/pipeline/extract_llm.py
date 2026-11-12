"""Field extraction with Claude (vision for images/scans, text for digital PDFs)."""

import json
import time
from dataclasses import dataclass

import anthropic

from app.config import get_settings
from app.pipeline.preprocess import PreparedDocument
from app.schemas import CATEGORIES, InvoiceExtraction

# USD per million tokens (input, output). Used for cost tracking only.
PRICING = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-fable-5-2": (8.00, 40.00),
    "gpt-6-astra": (10.00, 50.00),
    "gpt-6.1-sol": (2.00, 10.00),
    "gpt-6.1-terra": (1.00, 5.00),
    "gpt-6-luna": (0.10, 0.50),
}

SYSTEM_PROMPT = f"""You extract structured data from invoices and receipts for bookkeeping.

Rules:
- Copy values exactly as printed; do not invent data. Use null when a field is not on the document.
- Dates: convert to ISO YYYY-MM-DD. If the day/month order is ambiguous, prefer the order implied by the
  vendor's country or currency, and lower the invoice_date confidence.
- Amounts: plain numbers without currency symbols or thousands separators. Discounts are negative line items.
- subtotal is before tax; total is the final amount due. Shipping or fees printed as separate lines are line items.
- currency: ISO 4217 code inferred from symbols and context.
- line_items: one entry per billed row. Leave quantity/unit_price null if not printed.
- category: the best bookkeeping category from: {", ".join(CATEGORIES)}.
- doc_type: "other" if this is not an invoice or receipt.
- field_confidence: your honest 0-1 confidence per field. Use < 0.7 when text is blurry, cut off, handwritten,
  or you had to infer the value."""


class ExtractionError(RuntimeError):
    pass


@dataclass
class ExtractionResult:
    data: InvoiceExtraction
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    mode: str  # "vision" | "text"


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    in_price, out_price = PRICING.get(model, (0.0, 0.0))
    return round((input_tokens * in_price + output_tokens * out_price) / 1_000_000, 6)


def build_content(doc: PreparedDocument, use_text_mode: bool) -> tuple[list[dict], str]:
    if use_text_mode and doc.text:
        return [{"type": "text", "text": f"Document text (extracted from a digital PDF):\n\n{doc.text}"}], "text"
    if doc.kind == "pdf":
        block = {"type": "document", "source": {"type": "base64", "media_type": doc.media_type, "data": doc.b64}}
    else:
        block = {"type": "image", "source": {"type": "base64", "media_type": doc.media_type, "data": doc.b64}}
    return [block], "vision"


def correction_prompt(previous: InvoiceExtraction, problems: list[str]) -> str:
    return (
        "A previous extraction of this document failed validation.\n\n"
        f"Previous extraction:\n{previous.model_dump_json(indent=2)}\n\n"
        "Problems found:\n" + "\n".join(f"- {p}" for p in problems) + "\n\n"
        "Re-read the document carefully, paying special attention to the fields above, and return a corrected "
        "extraction. If the document itself is inconsistent (e.g. the printed total really does not match), keep "
        "the printed values and lower the relevant confidence instead of altering numbers."
    )


class ClaudeExtractor:
    def __init__(self, client: anthropic.Anthropic | None = None, model: str | None = None):
        settings = get_settings()
        # An explicit key from backend/.env wins; otherwise the SDK's own env/profile lookup applies
        self.client = client or (
            anthropic.Anthropic(api_key=settings.anthropic_api_key) if settings.anthropic_api_key else anthropic.Anthropic()
        )
        self.model = model or settings.llm_model
        self.effort = settings.llm_effort
        self.fallbacks = settings.llm_fallbacks
        self.text_mode = settings.use_pdf_text_mode

    def extract(
        self,
        doc: PreparedDocument,
        previous: InvoiceExtraction | None = None,
        problems: list[str] | None = None,
        force_vision: bool = False,
    ) -> ExtractionResult:
        content, mode = build_content(doc, use_text_mode=self.text_mode and not force_vision)
        instruction = (
            correction_prompt(previous, problems or [])
            if previous is not None
            else "Extract the invoice/receipt data from this document."
        )
        content = [*content, {"type": "text", "text": instruction}]

        kwargs: dict = dict(
            model=self.model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
            output_format=InvoiceExtraction,
            output_config={"effort": self.effort},
        )
        if self.fallbacks:
            kwargs["betas"] = ["server-side-fallback-2026-07-01"]
            kwargs["fallbacks"] = "default"

        started = time.perf_counter()
        try:
            response = self.client.beta.messages.parse(**kwargs)
        except anthropic.AuthenticationError as exc:
            raise ExtractionError("Anthropic authentication failed - set ANTHROPIC_API_KEY.") from exc
        except anthropic.BadRequestError as exc:
            raise ExtractionError(f"Model rejected the request: {exc.message}") from exc
        except anthropic.RateLimitError as exc:
            raise ExtractionError("Rate limited by the model API; retry later.") from exc
        except anthropic.APIStatusError as exc:
            raise ExtractionError(f"Model API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise ExtractionError("Could not reach the model API.") from exc
        latency_ms = int((time.perf_counter() - started) * 1000)

        if response.stop_reason == "refusal":
            raise ExtractionError("The model declined to process this document.")
        if response.stop_reason == "max_tokens":
            raise ExtractionError("Extraction was cut off (document too long).")
        data = response.parsed_output
        if data is None:  # defensive: parse failed silently
            text = next((b.text for b in response.content if b.type == "text"), "")
            data = InvoiceExtraction.model_validate(json.loads(text))

        usage = response.usage
        served_model = getattr(response, "model", self.model) or self.model
        return ExtractionResult(
            data=data,
            model=served_model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=estimate_cost(served_model, usage.input_tokens, usage.output_tokens),
            latency_ms=latency_ms,
            mode=mode,
        )

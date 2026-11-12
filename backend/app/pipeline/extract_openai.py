"""Field extraction with OpenAI (Chat Completions + structured outputs).

Same contract as ClaudeExtractor, so the orchestrator, validation and self-correction
loop work unchanged. Select it with EXTRACTOR=openai.
"""

import os
import time

import openai

from app.config import get_settings
from app.pipeline.extract_llm import (
    SYSTEM_PROMPT,
    ExtractionError,
    ExtractionResult,
    correction_prompt,
    estimate_cost,
)
from app.pipeline.preprocess import PreparedDocument
from app.schemas import InvoiceExtraction


def build_openai_content(doc: PreparedDocument, use_text_mode: bool) -> tuple[list[dict], str]:
    if use_text_mode and doc.text:
        return [{"type": "text", "text": f"Document text (extracted from a digital PDF):\n\n{doc.text}"}], "text"
    data_url = f"data:{doc.media_type};base64,{doc.b64}"
    if doc.kind == "pdf":
        return [{"type": "file", "file": {"filename": "document.pdf", "file_data": data_url}}], "vision"
    return [{"type": "image_url", "image_url": {"url": data_url, "detail": "high"}}], "vision"


class OpenAIExtractor:
    def __init__(self, client: openai.OpenAI | None = None, model: str | None = None):
        settings = get_settings()
        if client is None:
            if not (settings.openai_api_key or os.environ.get("OPENAI_API_KEY")):
                raise ExtractionError("OPENAI_API_KEY is not set (add it to backend/.env).")
            client = openai.OpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else openai.OpenAI()
        self.client = client
        self.model = model or settings.openai_model
        self.reasoning_effort = settings.openai_reasoning_effort
        self.text_mode = settings.use_pdf_text_mode

    def extract(
        self,
        doc: PreparedDocument,
        previous: InvoiceExtraction | None = None,
        problems: list[str] | None = None,
        force_vision: bool = False,
    ) -> ExtractionResult:
        content, mode = build_openai_content(doc, use_text_mode=self.text_mode and not force_vision)
        instruction = (
            correction_prompt(previous, problems or [])
            if previous is not None
            else "Extract the invoice/receipt data from this document."
        )
        kwargs: dict = dict(
            model=self.model,
            max_completion_tokens=16000,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": [*content, {"type": "text", "text": instruction}]},
            ],
            response_format=InvoiceExtraction,
        )
        if self.reasoning_effort:
            kwargs["reasoning_effort"] = self.reasoning_effort

        started = time.perf_counter()
        try:
            response = self.client.chat.completions.parse(**kwargs)
        except openai.AuthenticationError as exc:
            raise ExtractionError("OpenAI authentication failed - set OPENAI_API_KEY.") from exc
        except openai.LengthFinishReasonError as exc:
            raise ExtractionError("Extraction was cut off (document too long).") from exc
        except openai.ContentFilterFinishReasonError as exc:
            raise ExtractionError("The model declined to process this document.") from exc
        except openai.BadRequestError as exc:
            raise ExtractionError(f"Model rejected the request: {exc.message}") from exc
        except openai.RateLimitError as exc:
            raise ExtractionError("Rate limited (or out of credit) on the OpenAI API; retry later.") from exc
        except openai.APIStatusError as exc:
            raise ExtractionError(f"OpenAI API error {exc.status_code}: {exc.message}") from exc
        except openai.APIConnectionError as exc:
            raise ExtractionError("Could not reach the OpenAI API.") from exc
        latency_ms = int((time.perf_counter() - started) * 1000)

        message = response.choices[0].message
        if message.refusal:
            raise ExtractionError(f"The model declined to process this document: {message.refusal}")
        if message.parsed is None:
            raise ExtractionError("The model returned no structured data.")

        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0
        return ExtractionResult(
            data=message.parsed,
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=estimate_cost(self.model, input_tokens, output_tokens),
            latency_ms=latency_ms,
            mode=mode,
        )

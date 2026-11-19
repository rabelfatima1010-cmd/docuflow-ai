from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    # Storage
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'data' / 'docuflow.db').as_posix()}"
    storage_dir: Path = BACKEND_DIR / "data" / "uploads"
    max_upload_mb: int = 20

    # Extraction
    extractor: Literal["claude", "openai", "mock"] = "claude"
    # API keys: read from backend/.env (or the environment) and passed to the SDK clients
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    # Claude
    llm_model: str = "claude-opus-5-5"
    llm_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    llm_fallbacks: bool = True  # server-side refusal fallback (beta)
    # OpenAI
    openai_model: str = "gpt-6.1-sol"
    openai_reasoning_effort: Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"] | None = None
    max_correction_attempts: int = 2
    auto_approve_threshold: float = 0.90
    use_pdf_text_mode: bool = True  # PDFs with a real text layer go as text (cheaper)

    # Queue: leave empty to process in-process (dev); set for Redis + RQ workers
    redis_url: str | None = None

    # API
    cors_origins: str = "http://localhost:3000"
    webhook_secret: str | None = None

    # Public hosting safeguards
    # When set, uploads and review actions need this code (header X-Access-Code). Browsing stays open.
    upload_access_code: str | None = None
    daily_upload_limit: int = 40  # AI runs per day for the whole site (uploads + re-runs); 0 = unlimited
    per_ip_daily_limit: int = 10  # AI runs per day per visitor IP; 0 = unlimited
    max_pdf_pages: int = 5

    # Web UI: the built frontend (next build -> frontend/out) is served at "/" when present
    frontend_dir: Path = REPO_DIR / "frontend" / "out"
    # On startup, load the sample invoices from a real AI run into an empty database
    seed_demo: bool = True
    seed_dir: Path = REPO_DIR / "frontend" / "public" / "demo"

    # Exports
    export_on_approve: bool = True
    google_service_account_file: str | None = None
    google_sheet_id: str | None = None
    google_worksheet: str = "Invoices"
    n8n_export_webhook_url: str | None = None

    @property
    def active_model(self) -> str:
        return {"claude": self.llm_model, "openai": self.openai_model}.get(self.extractor, "mock")


@lru_cache
def get_settings() -> Settings:
    return Settings()

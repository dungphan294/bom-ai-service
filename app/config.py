"""Runtime settings, read from environment variables."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    llm_api_key: str | None
    llm_base_url: str | None
    llm_model: str
    max_upload_mb: int


def get_settings() -> Settings:
    return Settings(
        # Any OpenAI-compatible provider works: OpenAI, Groq (free tier), Ollama, ...
        llm_api_key=os.getenv("LLM_API_KEY") or None,
        llm_base_url=os.getenv("LLM_BASE_URL") or None,
        llm_model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
        max_upload_mb=int(os.getenv("MAX_UPLOAD_MB", "5")),
    )

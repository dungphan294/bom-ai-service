"""LLM client with a mock fallback.

With LLM_API_KEY set, calls any OpenAI-compatible API. Without a key it runs in
"mock" mode using simple rules, so the service, tests and demo work for free.
"""

import json
import re

from .config import get_settings
from .schemas import BomSummary, PartSpec


class LLMError(RuntimeError):
    """Raised when the LLM provider fails or returns unusable output."""


EXTRACT_PROMPT = (
    "You extract manufacturing part data from customer text. "
    "Reply with a JSON object only, with keys: part_name, material, quantity (integer), "
    "dimensions_mm, supplier, deadline (YYYY-MM-DD if possible), notes. Use null when unknown."
)

SUMMARY_PROMPT = (
    "You are an engineering assistant. Given BOM statistics as JSON, write a short "
    "summary (max 120 words) for a project engineer: the main materials by weight, "
    "anything unusual, missing data that must be fixed, and one practical suggestion "
    "(e.g. recycling or cost). Plain text, no markdown."
)


class LLMClient:
    def __init__(self, client=None, model: str | None = None):
        settings = get_settings()
        self.model = model or settings.llm_model
        self._client = client
        if self._client is None and settings.llm_api_key:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=settings.llm_api_key,
                base_url=settings.llm_base_url,
                timeout=30,
                max_retries=2,
            )

    @property
    def mode(self) -> str:
        return "live" if self._client else "mock"

    def _chat(self, system: str, user: str, json_mode: bool = False) -> str:
        kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                temperature=0,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                **kwargs,
            )
        except Exception as exc:  # provider/network errors
            raise LLMError(f"LLM request failed: {exc.__class__.__name__}") from exc
        return (resp.choices[0].message.content or "").strip()

    def extract_part(self, text: str) -> PartSpec:
        if not self._client:
            return mock_extract(text)
        raw = self._chat(EXTRACT_PROMPT, text, json_mode=True)
        try:
            return PartSpec.model_validate(_parse_json(raw))
        except ValueError as exc:
            raise LLMError("LLM returned invalid JSON") from exc

    def summarize_bom(self, summary: BomSummary) -> str:
        if not self._client:
            return mock_summary(summary)
        stats = summary.model_dump(exclude={"items"})
        stats["top_parts_by_weight"] = [
            {"part": i.part_number, "description": i.description, "total_kg": i.total_weight_kg}
            for i in sorted(summary.items, key=lambda i: i.total_weight_kg or 0, reverse=True)[:5]
        ]
        return self._chat(SUMMARY_PROMPT, json.dumps(stats))


def _parse_json(raw: str) -> dict:
    # Some models wrap JSON in ```json fences even in JSON mode.
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")
    return data


# ---------- mock mode (no API key) ----------

MATERIALS = [
    "stainless steel", "rvs", "steel", "aluminium", "aluminum", "copper", "brass",
    "hdpe", "pp", "pe", "pvc", "abs", "rubber",
]


def mock_extract(text: str) -> PartSpec:
    lower = text.lower()
    qty = re.search(r"(\d+)\s*(?:pcs|pieces|stuks|units|x\b)", lower)
    dims = re.search(r"(\d+(?:[.,]\d+)?\s*x\s*\d+(?:[.,]\d+)?(?:\s*x\s*\d+(?:[.,]\d+)?)?)\s*mm", lower)
    date = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    supplier = re.search(r"supplier:\s*([^\n.,;]+)", text, re.IGNORECASE)
    part = re.search(r"(?:of the|of)\s+([a-z][a-z \-]{2,40}?)\s+(?:in|made|from|,)", lower)
    material = next((m for m in MATERIALS if re.search(rf"\b{re.escape(m)}\b", lower)), None)
    return PartSpec(
        part_name=part.group(1).strip() if part else None,
        material=material,
        quantity=int(qty.group(1)) if qty else None,
        dimensions_mm=re.sub(r"\s+", "", dims.group(1)) if dims else None,
        supplier=supplier.group(1).strip() if supplier else None,
        deadline=date.group(1) if date else None,
        notes="Extracted in mock mode (rule-based). Set LLM_API_KEY for AI extraction.",
    )


def mock_summary(s: BomSummary) -> str:
    parts = [f"The BOM has {s.total_lines} lines and {s.total_quantity:g} parts in total."]
    if s.weight_by_material_kg:
        top, kg = next(iter(s.weight_by_material_kg.items()))
        parts.append(f"The heaviest material is {top} with {kg:g} kg.")
    if s.total_weight_kg is not None:
        parts.append(f"Total weight is {s.total_weight_kg:g} kg.")
    if s.missing_data:
        parts.append(f"{len(s.missing_data)} data issue(s) need fixing before ordering.")
    parts.append("(Mock summary: set LLM_API_KEY for an AI-written summary.)")
    return " ".join(parts)

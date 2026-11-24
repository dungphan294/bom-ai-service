"""FastAPI entry point."""

from functools import lru_cache
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import Response

from . import __version__
from .bom import BomError, parse_bom, summarize
from .config import get_settings
from .llm import LLMClient, LLMError
from .report import build_report
from .schemas import BomAnalysis, ExtractRequest, ExtractResponse

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

app = FastAPI(
    title="BOM AI Service",
    version=__version__,
    description=(
        "Microservice that uses an LLM to turn engineering data into useful output: "
        "extract part specs from customer text, analyse Excel BOMs and generate Word reports."
    ),
)


@lru_cache
def get_llm() -> LLMClient:
    return LLMClient()


async def _read_xlsx(file: UploadFile) -> bytes:
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(415, "Upload an .xlsx file")
    limit = get_settings().max_upload_mb * 1024 * 1024
    content = await file.read(limit + 1)
    if len(content) > limit:
        raise HTTPException(413, f"File larger than {get_settings().max_upload_mb} MB")
    return content


def _analyse(content: bytes, llm: LLMClient) -> BomAnalysis:
    try:
        summary = summarize(parse_bom(content))
    except BomError as exc:
        raise HTTPException(422, str(exc)) from exc
    try:
        ai_summary = llm.summarize_bom(summary)
    except LLMError as exc:
        raise HTTPException(502, str(exc)) from exc
    return BomAnalysis(summary=summary, ai_summary=ai_summary, llm_mode=llm.mode)


@app.get("/health")
def health(llm: LLMClient = Depends(get_llm)) -> dict:
    return {"status": "ok", "version": __version__, "llm_mode": llm.mode}


@app.post("/v1/extract", response_model=ExtractResponse)
def extract(req: ExtractRequest, llm: LLMClient = Depends(get_llm)) -> ExtractResponse:
    """Turn a free-text customer request into structured part data."""
    try:
        data = llm.extract_part(req.text)
    except LLMError as exc:
        raise HTTPException(502, str(exc)) from exc
    return ExtractResponse(data=data, llm_mode=llm.mode)


@app.post("/v1/bom/analyze", response_model=BomAnalysis)
async def analyze_bom(file: UploadFile = File(...), llm: LLMClient = Depends(get_llm)) -> BomAnalysis:
    """Upload an Excel BOM; get totals, weight per material, data issues and an AI summary."""
    return _analyse(await _read_xlsx(file), llm)


@app.post("/v1/bom/report", response_class=Response)
async def bom_report(file: UploadFile = File(...), llm: LLMClient = Depends(get_llm)) -> Response:
    """Upload an Excel BOM; download a Word report."""
    analysis = _analyse(await _read_xlsx(file), llm)
    stem = Path(file.filename or "bom").stem
    return Response(
        content=build_report(analysis, file.filename or "bom.xlsx"),
        media_type=DOCX_MIME,
        headers={"Content-Disposition": f'attachment; filename="{stem}_report.docx"'},
    )

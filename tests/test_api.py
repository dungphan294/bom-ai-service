from io import BytesIO
from types import SimpleNamespace

import pytest
from docx import Document
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.llm import LLMClient
from app.main import app, get_llm


def xlsx(rows: list[tuple]) -> bytes:
    wb = Workbook()
    for row in rows:
        wb.active.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


GOOD_BOM = xlsx([
    ("Part Number", "Description", "Materiaal", "Aantal", "Gewicht (kg)"),
    ("P-1", "Frame", "Steel", 2, 10.0),
    ("P-2", "Cover", "Aluminium", 4, 1.5),
    ("P-3", "Guard", None, 1, None),
])


class FakeOpenAI:
    """Mimics openai.OpenAI().chat.completions.create for live-mode tests."""

    def __init__(self, reply: str):
        self.reply = reply
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.reply))])


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    app.dependency_overrides[get_llm] = lambda: LLMClient()
    yield TestClient(app)
    app.dependency_overrides.clear()


def upload(client, path, content, name="bom.xlsx"):
    return client.post(path, files={"file": (name, content, "application/octet-stream")})


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["llm_mode"] == "mock"


def test_extract_mock(client):
    text = ("We need 250 pcs of the hopper bracket in stainless steel, 400 x 120 x 8 mm, "
            "before 2026-12-15. Supplier: MetaalTwente.")
    data = client.post("/v1/extract", json={"text": text}).json()["data"]
    assert data["quantity"] == 250
    assert data["material"] == "stainless steel"
    assert data["dimensions_mm"] == "400x120x8"
    assert data["deadline"] == "2026-12-15"
    assert data["supplier"] == "MetaalTwente"
    assert data["part_name"] == "hopper bracket"


def test_extract_rejects_empty(client):
    assert client.post("/v1/extract", json={"text": ""}).status_code == 422


def test_analyze_bom(client):
    r = upload(client, "/v1/bom/analyze", GOOD_BOM)
    assert r.status_code == 200
    s = r.json()["summary"]
    assert s["total_lines"] == 3
    assert s["total_quantity"] == 7
    assert s["total_weight_kg"] is None  # P-3 has no weight
    assert s["weight_by_material_kg"] == {"Steel": 20.0, "Aluminium": 6.0}
    assert "P-3: material missing" in s["missing_data"]
    assert "7 parts" in r.json()["ai_summary"]


def test_report_is_valid_docx(client):
    r = upload(client, "/v1/bom/report", GOOD_BOM, name="machine.xlsx")
    assert r.status_code == 200
    assert 'filename="machine_report.docx"' in r.headers["content-disposition"]
    text = "\n".join(p.text for p in Document(BytesIO(r.content)).paragraphs)
    assert "BOM Analysis Report" in text
    assert "P-3: weight missing" in text


@pytest.mark.parametrize("content,name,status,msg", [
    (b"hello", "bom.csv", 415, ".xlsx"),
    (b"not a workbook", "bom.xlsx", 422, "not a valid"),
    (xlsx([("Name", "Qty"), ("x", 1)]), "bom.xlsx", 422, "part_number"),
    (xlsx([("Part Number", "Description", "Qty")]), "bom.xlsx", 422, "no parts"),
    (xlsx([("Part Number", "Description", "Qty"), ("P", "D", "many")]), "bom.xlsx", 422, "not a number"),
])
def test_bad_uploads(client, content, name, status, msg):
    r = upload(client, "/v1/bom/analyze", content, name=name)
    assert r.status_code == status
    assert msg in r.json()["detail"]


def test_upload_size_limit(client, monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "0")
    assert upload(client, "/v1/bom/analyze", GOOD_BOM).status_code == 413


def test_live_mode_extract_parses_fenced_json():
    fake = FakeOpenAI('```json\n{"part_name": "bracket", "quantity": 5, "material": null}\n```')
    app.dependency_overrides[get_llm] = lambda: LLMClient(client=fake, model="test-model")
    try:
        r = TestClient(app).post("/v1/extract", json={"text": "5 brackets"})
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json() == {"data": {"part_name": "bracket", "material": None, "quantity": 5,
                                 "dimensions_mm": None, "supplier": None, "deadline": None,
                                 "notes": None}, "llm_mode": "live"}
    assert fake.calls[0]["model"] == "test-model"
    assert fake.calls[0]["response_format"] == {"type": "json_object"}


def test_live_mode_bad_json_returns_502():
    app.dependency_overrides[get_llm] = lambda: LLMClient(client=FakeOpenAI("sorry, no JSON"))
    try:
        r = TestClient(app).post("/v1/extract", json={"text": "x"})
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 502


def test_live_mode_summary_uses_llm():
    fake = FakeOpenAI("Steel dominates the weight.")
    app.dependency_overrides[get_llm] = lambda: LLMClient(client=fake)
    try:
        r = upload(TestClient(app), "/v1/bom/analyze", GOOD_BOM)
    finally:
        app.dependency_overrides.clear()
    assert r.json()["ai_summary"] == "Steel dominates the weight."
    assert r.json()["llm_mode"] == "live"


def test_web_page(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "BOM AI Service" in r.text


def test_sample_download_is_a_valid_bom(client):
    r = client.get("/sample.xlsx")
    assert r.status_code == 200
    assert upload(client, "/v1/bom/analyze", r.content).status_code == 200

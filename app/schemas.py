"""Request and response models."""

from pydantic import BaseModel, Field


class PartSpec(BaseModel):
    """Structured data extracted from a free-text request (e.g. a customer email)."""

    part_name: str | None = None
    material: str | None = None
    quantity: int | None = None
    dimensions_mm: str | None = None
    supplier: str | None = None
    deadline: str | None = None
    notes: str | None = None


class ExtractRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20_000, examples=[
        "Hi, we need 250 pcs of the hopper bracket in stainless steel, "
        "400 x 120 x 8 mm, delivered before 2026-12-15. Supplier: MetaalTwente."
    ])


class ExtractResponse(BaseModel):
    data: PartSpec
    llm_mode: str


class BomItem(BaseModel):
    part_number: str
    description: str
    material: str | None = None
    quantity: float
    unit_weight_kg: float | None = None

    @property
    def total_weight_kg(self) -> float | None:
        if self.unit_weight_kg is None:
            return None
        return self.unit_weight_kg * self.quantity


class BomSummary(BaseModel):
    items: list[BomItem]
    total_lines: int
    total_quantity: float
    total_weight_kg: float | None
    weight_by_material_kg: dict[str, float]
    missing_data: list[str]


class BomAnalysis(BaseModel):
    summary: BomSummary
    ai_summary: str
    llm_mode: str

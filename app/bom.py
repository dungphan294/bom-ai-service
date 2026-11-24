"""Parse an Excel bill of materials (BOM) and compute totals."""

from collections import defaultdict
from io import BytesIO
from zipfile import BadZipFile

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from .schemas import BomItem, BomSummary

# Accept English and Dutch column names, case-insensitive.
COLUMN_ALIASES: dict[str, set[str]] = {
    "part_number": {"part number", "part_number", "part no", "partno", "pn", "artikelnummer", "onderdeelnummer"},
    "description": {"description", "omschrijving", "name", "naam", "part name"},
    "material": {"material", "materiaal"},
    "quantity": {"quantity", "qty", "aantal"},
    "unit_weight_kg": {"unit weight (kg)", "unit weight", "weight (kg)", "weight_kg", "weight", "gewicht", "gewicht (kg)"},
}
REQUIRED = ("part_number", "description", "quantity")


class BomError(ValueError):
    """Raised when the uploaded file is not a usable BOM."""


def _map_headers(header_row: tuple) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for idx, cell in enumerate(header_row):
        if cell is None:
            continue
        name = str(cell).strip().lower()
        for field, aliases in COLUMN_ALIASES.items():
            if name in aliases and field not in mapping:
                mapping[field] = idx
    missing = [f for f in REQUIRED if f not in mapping]
    if missing:
        raise BomError(f"Missing required column(s): {', '.join(missing)}")
    return mapping


def _to_float(value, field: str, row_no: int) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        return float(str(value).replace(",", "."))
    except ValueError as exc:
        raise BomError(f"Row {row_no}: '{value}' is not a number in column {field}") from exc


def parse_bom(content: bytes) -> list[BomItem]:
    try:
        wb = load_workbook(BytesIO(content), read_only=True, data_only=True)
    except (InvalidFileException, BadZipFile, OSError, KeyError, ValueError) as exc:
        raise BomError("File is not a valid .xlsx workbook") from exc

    rows = wb.active.iter_rows(values_only=True)
    header = next(rows, None)
    if header is None:
        raise BomError("The sheet is empty")
    cols = _map_headers(header)

    items: list[BomItem] = []
    for row_no, row in enumerate(rows, start=2):
        if row is None or all(v is None for v in row):
            continue

        def get(field: str):
            i = cols.get(field)
            return row[i] if i is not None and i < len(row) else None

        part_number, description = get("part_number"), get("description")
        quantity = _to_float(get("quantity"), "quantity", row_no)
        if part_number is None or description is None or quantity is None:
            raise BomError(f"Row {row_no}: part number, description and quantity are required")
        material = get("material")
        items.append(BomItem(
            part_number=str(part_number).strip(),
            description=str(description).strip(),
            material=str(material).strip() if material else None,
            quantity=quantity,
            unit_weight_kg=_to_float(get("unit_weight_kg"), "unit_weight_kg", row_no),
        ))
    wb.close()

    if not items:
        raise BomError("The BOM has a header row but no parts")
    return items


def summarize(items: list[BomItem]) -> BomSummary:
    by_material: dict[str, float] = defaultdict(float)
    missing: list[str] = []
    total_weight = 0.0
    all_weights_known = True

    for item in items:
        if item.material is None:
            missing.append(f"{item.part_number}: material missing")
        weight = item.total_weight_kg
        if weight is None:
            all_weights_known = False
            missing.append(f"{item.part_number}: weight missing")
            continue
        total_weight += weight
        by_material[item.material or "Unknown"] += weight

    return BomSummary(
        items=items,
        total_lines=len(items),
        total_quantity=sum(i.quantity for i in items),
        total_weight_kg=round(total_weight, 3) if all_weights_known else None,
        weight_by_material_kg={k: round(v, 3) for k, v in sorted(by_material.items(), key=lambda kv: -kv[1])},
        missing_data=missing,
    )

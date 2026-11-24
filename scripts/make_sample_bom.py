"""Create sample_data/sample_bom.xlsx: a small recycling-machine BOM for demos."""

from pathlib import Path

from openpyxl import Workbook

ROWS = [
    ("RM-1001", "Shredder housing", "Steel", 1, 182.5),
    ("RM-1002", "Rotor shaft", "Stainless steel", 1, 46.0),
    ("RM-1003", "Cutting blade", "Tool steel", 24, 1.8),
    ("RM-1004", "Hopper side panel", "Steel", 4, 12.4),
    ("RM-1005", "Inspection cover", "Aluminium", 2, 3.1),
    ("RM-1006", "Conveyor belt", "Rubber", 1, 28.0),
    ("RM-1007", "Bearing 6310", "Steel", 2, 1.05),
    ("RM-1008", "Cable gland M20", "PA", 12, 0.02),
    ("RM-1009", "Safety guard", "Polycarbonate", 2, None),
    ("RM-1010", "Motor bracket", None, 1, 7.6),
]


def main() -> Path:
    out = Path(__file__).resolve().parent.parent / "sample_data" / "sample_bom.xlsx"
    out.parent.mkdir(exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "BOM"
    ws.append(["Part Number", "Description", "Material", "Qty", "Unit Weight (kg)"])
    for row in ROWS:
        ws.append(row)
    wb.save(out)
    return out


if __name__ == "__main__":
    print(f"Wrote {main()}")

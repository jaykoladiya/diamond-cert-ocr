"""Write extracted certificate records to Excel: a fresh workbook, or appended to an
uploaded one (columns matched by header name, so an existing stock sheet keeps its layout)."""
import io
import re

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .extract import FIELDS

EXTRA = [("source_file", "Source File")]
COLUMNS = FIELDS + EXTRA

# Other header spellings an existing sheet might use.
ALIASES = {
    "lab": ["laboratory", "lab", "cert lab", "grading lab"],
    "report_number": ["report no", "report number", "cert no", "certificate no", "certificate number",
                      "cert number", "report #", "cert #", "certificate"],
    "report_date": ["date", "cert date", "report date", "issue date"],
    "origin": ["natural/lab grown", "type", "natural / lab-grown", "origin", "natural or lab"],
    "growth_method": ["growth", "growth method", "method"],
    "shape": ["shape", "shape & cutting style", "shape and cutting style", "cut style"],
    "measurements": ["measurements", "measurement", "dimensions", "mm"],
    "length_mm": ["length", "length (mm)", "l"],
    "width_mm": ["width", "width (mm)", "w"],
    "depth_mm": ["depth (mm)", "height", "depth mm"],
    "carat": ["carat", "carats", "weight", "carat weight", "cts", "ct"],
    "color": ["color", "colour", "color grade", "colour grade"],
    "clarity": ["clarity", "clarity grade"],
    "cut": ["cut", "cut grade"],
    "polish": ["polish", "pol"],
    "symmetry": ["symmetry", "sym"],
    "fluorescence": ["fluorescence", "fluor", "flr", "fluo"],
    "depth_pct": ["depth %", "depth%", "total depth", "depth"],
    "table_pct": ["table %", "table%", "table"],
    "crown_angle": ["crown angle", "crown"],
    "pavilion_angle": ["pavilion angle", "pavilion"],
    "girdle": ["girdle"],
    "culet": ["culet"],
    "inscription": ["inscription", "inscriptions", "laser inscription"],
    "comments": ["comments", "comment", "remarks", "notes"],
    "source_file": ["source file", "file", "filename"],
}


def _norm(h):
    return re.sub(r"[^a-z0-9%#&/]+", " ", str(h or "").lower()).strip()


def _header_map(ws):
    """Find the header row in the first 15 rows; return (row_index, {field_key: col})."""
    lookup = {}
    for key, header in COLUMNS:
        for name in [header] + ALIASES.get(key, []):
            lookup.setdefault(_norm(name), key)
    best = (None, {})
    for r in range(1, min(ws.max_row, 15) + 1):
        mapping = {}
        for c in range(1, ws.max_column + 1):
            key = lookup.get(_norm(ws.cell(r, c).value))
            if key and key not in mapping:
                mapping[key] = c
        if len(mapping) > len(best[1]):
            best = (r, mapping)
    return best if len(best[1]) >= 2 else (None, {})


def _last_data_row(ws, start, cols):
    last = start
    for r in range(start + 1, ws.max_row + 1):
        if any(ws.cell(r, c).value not in (None, "") for c in cols):
            last = r
    return last


def _style_header(ws, row, ncols):
    fill = PatternFill("solid", fgColor="1F3A5F")
    for c in range(1, ncols + 1):
        cell = ws.cell(row, c)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def build_workbook(records, template_bytes=None):
    """Return (xlsx_bytes, info) where info says how rows were written."""
    if template_bytes:
        wb = load_workbook(io.BytesIO(template_bytes))
        ws = wb.worksheets[0]
        header_row, mapping = _header_map(ws)
        if header_row:
            # add any of our columns the sheet lacks, at the right-hand end
            added = []
            for key, header in COLUMNS:
                if key not in mapping:
                    col = ws.max_column + 1
                    ws.cell(header_row, col, header)
                    mapping[key] = col
                    added.append(header)
            row = _last_data_row(ws, header_row, mapping.values())
            for rec in records:
                row += 1
                for key, col in mapping.items():
                    ws.cell(row, col, rec.get(key))
            buf = io.BytesIO()
            wb.save(buf)
            return buf.getvalue(), {"mode": "appended", "sheet": ws.title, "rows": len(records),
                                    "added_columns": added}
        ws = wb.create_sheet("Diamond Certificates")
    else:
        wb = Workbook()
        ws = wb.active
        ws.title = "Diamond Certificates"

    for c, (_, header) in enumerate(COLUMNS, 1):
        ws.cell(1, c, header)
    _style_header(ws, 1, len(COLUMNS))
    for r, rec in enumerate(records, 2):
        for c, (key, _) in enumerate(COLUMNS, 1):
            ws.cell(r, c, rec.get(key))
    for c, (key, header) in enumerate(COLUMNS, 1):
        width = max([len(header)] + [len(str(rec.get(key) or "")) for rec in records])
        ws.column_dimensions[get_column_letter(c)].width = min(max(width + 2, 10), 60)
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNS))}{max(1, len(records) + 1)}"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), {"mode": "new", "sheet": ws.title, "rows": len(records)}

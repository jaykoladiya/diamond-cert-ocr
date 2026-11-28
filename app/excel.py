"""Write extracted certificate records to Excel: a fresh workbook, or appended to an
uploaded one (columns matched by header name, so an existing stock sheet keeps its layout)."""
import io
import re

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .extract import FIELDS

# Stock-list layout: these columns first, in this order, with short codes ...
FRONT = [("shape", "Shape"), ("carat", "Ct."), ("color", "Clr"), ("clarity", "Clrty"), ("cut", "C"),
         ("polish", "P"), ("symmetry", "SYM"), ("fluorescence", "FLT"), ("lab", "Lab"), ("report_number", "Cert")]
# ... then every other extracted field, with full headers.
_front_keys = {k for k, _ in FRONT}
COLUMNS = FRONT + [(k, h) for k, h in FIELDS if k not in _front_keys] + [("source_file", "Source File")]
NUMERIC_FORMATS = {"carat": "0.00", "length_mm": "0.00", "width_mm": "0.00", "depth_mm": "0.00",
                   "depth_pct": "0.0", "table_pct": "0.0", "crown_angle": "0.0", "pavilion_angle": "0.0",
                   "crown_height": "0.0", "pavilion_depth": "0.0"}
FLUOR_COLORS = {"blue": "B", "white": "W", "yellow": "Y", "orange": "O", "red": "R", "green": "G"}
FANCY_INTENSITIES = ["fancy light", "fancy intense", "fancy vivid", "fancy deep", "fancy dark", "very light",
                     "fancy", "faint", "light"]

GRADE_CODES = {"ideal": "ID", "excellent": "EX", "very good": "VG", "good": "G", "fair": "F", "poor": "P"}
FLUOR_CODES = {"none": "NON", "nil": "NON", "inert": "NON", "negligible": "FNT", "faint": "FNT",
               "very slight": "VSL", "slight": "SL",
               "medium": "MED", "moderate": "MED", "strong": "STG", "very strong": "VST"}
# GIA/IGI "shape and cutting style" -> trade shape name; first match wins
# GIA/IGI "shape and cutting style" -> Rapaport Trade shape name; first match wins. GIA's
# square/rectangular brilliants follow Rapaport's "GIA shapes and trade shapes" table.
SHAPES = [
    (r"cut[- ]?cornered\s+square\s+modified", "Square Radiant"),
    (r"cut[- ]?cornered\s+rectangular\s+modified|\bradiant", "Radiant"),
    (r"round[- ]?cornered\s+rectangular\s+modified|modified\s+rectangular\s+brilliant", "Other"),
    (r"^\s*rectangular\s+modified\s+brilliant", "Radiant"),
    (r"^\s*modified\s+square\s+brilliant", "Cushion Modified"),
    (r"\bprincess|square\s+modified\s+brilliant", "Princess"),
    (r"\basscher", "Asscher"), (r"square\s+emerald", "Square Emerald"), (r"\bemerald", "Emerald"),
    (r"cushion\s+modified", "Cushion Modified"), (r"cushion\s+brilliant", "Cushion Brilliant"),
    (r"\bcushion", "Cushion Modified"),
    (r"\bround", "Round"), (r"\boval", "Oval"), (r"\bpear", "Pear"),
    (r"\bmarquise", "Marquise"), (r"\bheart", "Heart"), (r"\btrilliant", "Trilliant"),
    (r"\btriang", "Triangle"), (r"tapered\s+baguette", "Tapered Baguette"), (r"\bbaguette", "Baguette"),
    (r"old\s*european|\beuropean", "European Cut"), (r"old\s*mine", "Old Miner"),
    (r"\brose", "Rose"), (r"\bhalf\s*moon", "Half Moon"), (r"\bkite", "Kite"), (r"\bshield", "Shield"),
    (r"\bhexagon", "Hexagonal"), (r"\boctagon", "Octagonal"), (r"\bbriolette", "Briolette"),
    (r"\btrapez", "Trapezoid"), (r"\blozenge", "Lozenge"), (r"\bstar\b", "Star"),
    (r"^\s*square\b", "Square"),
]


def _code(value, codes):
    v = re.sub(r"\s+", " ", str(value).strip().lower())
    if v.upper() in set(codes.values()):
        return v.upper()
    for word in sorted(codes, key=len, reverse=True):  # "very good" before "good"
        if v.startswith(word) or v.replace(" ", "").startswith(word.replace(" ", "")):  # "VERYGOOD"
            return codes[word]
    return value


def verify_url(lab, cert):
    """Official online report check for a GIA or IGI report number (opens in a browser)."""
    from urllib.parse import quote
    cert = re.sub(r"\s+", "", str(cert or ""))
    lab = str(lab or "").upper()
    if not cert:
        return None
    if lab == "GIA":
        return "https://www.gia.edu/report-check?reportno=" + quote(cert)
    if lab == "IGI":
        return "https://www.igi.org/verify-your-report/?r=" + quote(cert)
    return None


def _link(cell, rec):
    url = verify_url(rec.get("lab"), rec.get("report_number"))
    if url:
        cell.hyperlink = url
        cell.font = Font(color="0563C1", underline="single")


def format_record(rec):
    """Record in the stock-list style: Round, EX/VG/G, NON/FNT/MED/STG/VST, carat as a number.
    Safe to apply more than once (already-short values pass through)."""
    out = dict(rec)
    if out.get("shape"):
        for rx, name in SHAPES:
            if re.search(rx, str(out["shape"]), re.I):
                out["shape"] = name
                break
    for key in ("cut", "polish", "symmetry"):
        if out.get(key):
            out[key] = _code(out[key], GRADE_CODES)
    if out.get("fluorescence"):
        m = re.search(r"\b(" + "|".join(FLUOR_COLORS) + r")\b", str(out["fluorescence"]), re.I)
        if m and not out.get("fluor_color"):  # "Medium Blue" -> FLT MED, Flr Color B
            out["fluor_color"] = FLUOR_COLORS[m.group(1).lower()]
        from .extract import RAP_FLUOR
        raw = re.sub(r"[\s.]", "", str(out["fluorescence"])).upper()
        out["fluorescence"] = _code(RAP_FLUOR.get(raw, out["fluorescence"]), FLUOR_CODES)
    if out.get("fluorescence") == "NON" and not out.get("fluor_color"):
        out["fluor_color"] = "N"
    color = str(out.get("color") or "")
    if color and not re.fullmatch(r"[D-Z](-[D-Z])?", color) and not out.get("fancy_color"):
        # "Fancy Intense Yellowish Brown" -> intensity / overtone / colour, as Rapaport splits it
        rest = color.lower()
        for word in FANCY_INTENSITIES:
            if rest.startswith(word):
                out["fancy_intensity"] = word.title()
                rest = rest[len(word):].strip()
                break
        words = rest.replace("-", " ").split()
        overtones = [w for w in words[:-1] if w.endswith(("ish", "y"))]
        out["fancy_overtone"] = " ".join(w.title() for w in overtones) or None
        main = [w for w in words if w not in overtones]
        out["fancy_color"] = " ".join(w.title() for w in main) or None
    for key in NUMERIC_FORMATS:
        v = out.get(key)
        if isinstance(v, str) and re.fullmatch(r"\s*\d+(?:[.,]\d+)?\s*", v):
            out[key] = float(v.replace(",", "."))
    return out

# Other header spellings an existing sheet might use.
ALIASES = {
    "lab": ["laboratory", "lab", "cert lab", "grading lab"],
    # short stock-list headers: Shape | Ct. | Clr | Clrty | C | P | SYM | FLT | Lab | Cert
    "report_number": ["report no", "report number", "cert no", "certificate no", "certificate number",
                      "cert number", "report #", "cert #", "certificate", "cert", "report"],
    "report_date": ["date", "cert date", "report date", "issue date"],
    "origin": ["natural/lab grown", "type", "natural / lab-grown", "origin", "natural or lab"],
    "growth_method": ["growth", "growth method", "method"],
    "shape": ["shape", "shape & cutting style", "shape and cutting style", "cut style"],
    "measurements": ["measurements", "measurement", "dimensions", "mm"],
    "length_mm": ["length", "length (mm)", "l"],
    "width_mm": ["width", "width (mm)", "w"],
    "depth_mm": ["depth (mm)", "height", "depth mm"],
    "carat": ["carat", "carats", "weight", "carat weight", "cts", "ct", "size"],
    "color": ["color", "colour", "color grade", "colour grade", "clr", "col"],
    "clarity": ["clarity", "clarity grade", "clrty", "clar", "cla"],
    "cut": ["cut", "cut grade", "c"],
    "polish": ["polish", "pol", "p"],
    "symmetry": ["symmetry", "sym"],
    "fluorescence": ["fluorescence", "fluor", "flr", "fluo", "flt", "fl"],
    "depth_pct": ["depth %", "depth%", "total depth", "depth"],
    "table_pct": ["table %", "table%", "table"],
    "crown_angle": ["crown angle", "crownangle"],
    "pavilion_angle": ["pavilion angle", "pavilionangle", "pav angle"],
    "girdle": ["girdle"],
    "culet": ["culet"],
    "inscription": ["inscription", "inscriptions", "laser inscription"],
    "comments": ["comments", "comment", "remarks", "notes"],
    "source_file": ["source file", "file", "filename"],
    "fluor_color": ["flr color", "fluor color", "fluorcolor", "fluo color", "flrcolor", "fluorescence color"],
    "fancy_color": ["fancy color", "fancycolor", "fc main body", "fcmainbody", "fancycolormainbody"],
    "fancy_intensity": ["fancy intensity", "fancy color intensity", "fancycolorintensity", "fcintensity",
                        "fc intensity"],
    "fancy_overtone": ["fancy overtone", "fancy color overtone", "fancycolorovertone", "fcovertone"],
    "crown_height": ["crown height", "crown height %", "crown", "crown percent", "crownheight", "crownpct"],
    "pavilion_depth": ["pavilion depth", "pavilion depth %", "pavilion %", "pavilionpct", "pavilion"],
}
# Rapaport Trade's accepted field names (help.rapaport.com, "Diamond Fields & Values")
for _k, _names in {
    "shape": ['shp'],
    "carat": ['sz', 'caratsize', 'caratweight', 'ctsize', 'ctweight'],
    "color": ['colr'],
    "clarity": ['clearity', 'purity'],
    "cut": ['cutgrade'],
    "polish": ['finish'],
    "symmetry": ['symetry', 'sym metry'],
    "fluorescence": ['fluorescence intensity', 'fluorescenceintensity', 'fluor intensity', 'fluorintensity', 'fluo intensity', 'flrintensity'],
    "report_number": ['certificate #', 'cert num', 'certid', 'certificateid', 'certificatenum', 'certificatenumber', 'certno', 'certnum'],
    "measurements": ['meas'],
    "length_mm": ['measlength', 'measurements length'],
    "width_mm": ['measwidth', 'measurements width'],
    "depth_mm": ['measdepth', 'measheight', 'measurements depth'],
    "depth_pct": ['depth percent', 'depthpct', 'depthpercent', 'dpth', 'totaldepth'],
    "table_pct": ['table percent', 'tablepct', 'tablepercent', 'tbl'],
    "culet": ['culet size', 'culetsize', 'culet size', 'culetgrade', 'cullet'],
    "comments": ['cert comment', 'certificate comment', 'lab comment', 'laboratory comment'],
    "report_date": ['report issue date'],
}.items():
    ALIASES.setdefault(_k, []).extend(_names)


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
    fill = PatternFill("solid", fgColor="C5D9F1")  # light blue, bold black: as in the stock list
    thin = Side(style="thin", color="000000")
    for c in range(1, ncols + 1):
        cell = ws.cell(row, c)
        cell.font = Font(bold=True, color="000000")
        cell.fill = fill
        cell.border = Border(left=thin, right=thin, top=thin, bottom=thin)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[row].height = 30


def build_workbook(records, template_bytes=None):
    """Return (xlsx_bytes, info) where info says how rows were written."""
    records = [format_record(r) for r in records]
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
                    cell = ws.cell(row, col, rec.get(key))
                    if key in NUMERIC_FORMATS and isinstance(rec.get(key), (int, float)):
                        cell.number_format = NUMERIC_FORMATS[key]
                    if key == "report_number":
                        _link(cell, rec)
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
    thin = Side(style="thin", color="000000")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(horizontal="center", vertical="center")
    for r, rec in enumerate(records, 2):
        for c, (key, _) in enumerate(COLUMNS, 1):
            cell = ws.cell(r, c, rec.get(key))
            cell.border = border
            if key in NUMERIC_FORMATS and isinstance(rec.get(key), (int, float)):
                cell.number_format = NUMERIC_FORMATS[key]
            if c <= len(FRONT) and key != "shape":
                cell.alignment = center
            if key == "report_number":
                _link(cell, rec)
    for c, (key, header) in enumerate(COLUMNS, 1):
        width = max([len(header)] + [len(str(rec.get(key) or "")) for rec in records])
        ws.column_dimensions[get_column_letter(c)].width = min(max(width + 2, 6 if c <= len(FRONT) else 10), 60)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNS))}{max(1, len(records) + 1)}"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), {"mode": "new", "sheet": ws.title, "rows": len(records)}

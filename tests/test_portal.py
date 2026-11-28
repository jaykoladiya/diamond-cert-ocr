import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from app import ocr
from app.excel import build_workbook, format_record
from app.extract import extract_fields
from app.main import app

FIX = Path(__file__).parent / "fixtures"


def fields(name):
    return extract_fields(ocr.convert((FIX / name).read_text()))


def test_gia_natural():
    r = fields("gia_natural.txt")
    assert r["lab"] == "GIA" and r["report_number"] == "2215487963"
    assert r["report_date"] == "2025-11-03" and r["origin"] == "Natural"
    assert r["shape"] == "Round Brilliant" and r["carat"] == 1.01
    assert (r["color"], r["clarity"], r["cut"]) == ("G", "VS1", "Excellent")
    assert (r["polish"], r["symmetry"], r["fluorescence"]) == ("Excellent", "Very Good", "Faint")
    assert (r["length_mm"], r["width_mm"], r["depth_mm"]) == (6.45, 6.48, 3.98)
    assert (r["table_pct"], r["depth_pct"], r["crown_angle"], r["pavilion_angle"]) == (57, 61.6, 34.5, 40.8)
    assert r["girdle"].startswith("Medium") and r["culet"] == "None"
    assert r["inscription"] == "GIA 2215487963"


def test_igi_labgrown():
    r = fields("igi_labgrown.txt")
    assert r["lab"] == "IGI" and r["report_number"] == "LG612345678"
    assert r["origin"] == "Lab-Grown" and r["growth_method"] == "CVD"
    assert r["shape"] == "Oval Brilliant" and r["carat"] == 1.52
    assert (r["color"], r["clarity"]) == ("E", "VVS2")
    assert r["report_date"] == "2025-08-15"
    assert (r["length_mm"], r["width_mm"], r["depth_mm"]) == (9.12, 6.35, 3.95)


def test_hrd_multi_column_table():
    r = fields("hrd_table.txt")
    assert r["lab"] == "HRD" and r["report_number"] == "220001234567"
    assert r["report_date"] == "2024-02-02" and r["carat"] == 0.70
    assert (r["shape"], r["color"], r["clarity"], r["cut"]) == ("Princess", "F", "SI1", "Very Good")
    assert r["fluorescence"] == "Medium Blue" and r["depth_pct"] == 73.7 and r["table_pct"] == 68


def test_color_scale_not_mistaken_for_grade():
    r = extract_fields("GIA COLOR SCALE D E F G H\nColor: D E F G H I J\nColor Grade ..... H")
    assert r["color"] == "H"


def test_excel_new_and_append():
    recs = [dict(fields("gia_natural.txt"), source_file="a.pdf")]
    data, info = build_workbook(recs)
    ws = load_workbook(io.BytesIO(data)).active
    assert info["mode"] == "new"
    # stock-list layout: these ten columns first, short codes, then the rest
    assert [c.value for c in ws[1]][:10] == ["Shape", "Ct.", "Clr", "Clrty", "C", "P", "SYM", "FLT", "Lab", "Cert"]
    assert [c.value for c in ws[2]][:10] == ["Round", 1.01, "G", "VS1", "EX", "EX", "VG", "FNT", "GIA", "2215487963"]
    assert ws["B2"].number_format == "0.00"
    headers = [c.value for c in ws[1]]
    assert headers[10:13] == ["Report Date", "Natural / Lab-Grown", "Growth Method"] and headers[-1] == "Source File"

    wb = Workbook(); s = wb.active
    s.append(["My Stock List"]); s.append([])
    s.append(["Stock #", "Cert No", "Carat", "Colour", "Clarity", "Price"])
    s.append(["S1", "999", 0.5, "D", "IF", 1000])
    buf = io.BytesIO(); wb.save(buf)
    data, info = build_workbook(recs, buf.getvalue())
    ws = load_workbook(io.BytesIO(data)).active
    assert info["mode"] == "appended"
    assert [c.value for c in ws[5]][:6] == [None, "2215487963", 1.01, "G", "VS1", None]
    assert ws.cell(4, 1).value == "S1"           # existing data untouched


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(ocr, "OCR_BACKEND", "unlimited")
    monkeypatch.setattr(ocr.requests.Session, "post", lambda self, url, **kw: _FakeResp())
    return TestClient(app)


class _FakeResp:
    status_code = 200
    def json(self):
        return {"choices": [{"message": {"content": (FIX / "igi_labgrown.txt").read_text()}}]}


def _png(w=40, h=40):
    from PIL import Image
    b = io.BytesIO(); Image.new("RGB", (w, h), "white").save(b, "PNG"); return b.getvalue()


def test_api_extract_and_export(client):
    r = client.post("/api/extract", files=[("files", ("cert.png", _png(), "image/png")),
                                           ("files", ("notes.txt", b"x", "text/plain"))]).json()
    ok, bad = r["results"]
    assert ok["record"]["report_number"] == "LG612345678" and ok["missing"] == []
    assert "Unsupported" in bad["error"]
    resp = client.post("/api/export", data={"records": json.dumps([ok["record"]])})
    assert resp.status_code == 200
    ws = load_workbook(io.BytesIO(resp.content)).active
    assert [c.value for c in ws[2]][:10] == ["Oval", 1.52, "E", "VVS2", None, "EX", "EX", "NON", "IGI", "LG612345678"]
    assert ok["record"]["shape"] == "Oval" and ok["record"]["fluorescence"] == "NON"  # on screen as in Excel


def test_pdf_pages():
    import pymupdf as fitz
    doc = fitz.open(); doc.new_page(); doc.new_page()
    pages = ocr.to_page_images("x.pdf", doc.tobytes())
    assert len(pages) == 2 and pages[0][0] == "image/png"


@pytest.mark.parametrize("shape,code", [
    ("Round Brilliant", "Round"), ("Cushion Modified Brilliant", "Cushion Modified"), ("Oval Brilliant", "Oval"),
    ("Square Modified Brilliant", "Princess"), ("Cut-Cornered Rectangular Modified Brilliant", "Radiant"),
    ("Emerald Cut", "Emerald"), ("Square Emerald Cut", "Square Emerald"), ("Pear Modified Brilliant", "Pear"),
    ("Round", "Round"), ("Some New Cut", "Some New Cut")])
def test_shape_codes(shape, code):
    assert format_record({"shape": shape})["shape"] == code


def test_grade_and_fluorescence_codes():
    r = format_record({"cut": "Very Good", "polish": "Excellent", "symmetry": "Good",
                       "fluorescence": "Medium Blue", "carat": "0.45"})
    assert (r["cut"], r["polish"], r["symmetry"], r["fluorescence"], r["carat"]) == ("VG", "EX", "G", "MED", 0.45)
    assert format_record(r) == r                     # already-short values stay as they are
    assert format_record({"fluorescence": "Very Strong"})["fluorescence"] == "VST"
    assert format_record({"fluorescence": "None"})["fluorescence"] == "NON"


def test_append_to_short_header_stock_list():
    """A sheet laid out like the stock list (Shape | Ct. | Clr | ...) gets rows under its own headers."""
    wb = Workbook(); s = wb.active
    s.append(["Shape", "Ct.", "Clr", "Clrty", "C", "P", "SYM", "FLT", "Lab", "Cert"])
    s.append(["Round", 0.45, "F", "IF", "EX", "EX", "EX", "NON", "GIA", "1495557172"])
    buf = io.BytesIO(); wb.save(buf)
    data, info = build_workbook([dict(fields("gia_natural.txt"), source_file="a.pdf")], buf.getvalue())
    ws = load_workbook(io.BytesIO(data)).active
    assert [c.value for c in ws[3]][:10] == ["Round", 1.01, "G", "VS1", "EX", "EX", "VG", "FNT", "GIA", "2215487963"]
    assert [c.value for c in ws[2]][:2] == ["Round", 0.45]      # existing row untouched
    assert "Report Date" in info["added_columns"]               # the rest are added after


def test_verify_links():
    from app.excel import verify_url
    assert verify_url("GIA", "2517492150") == "https://www.gia.edu/report-check?reportno=2517492150"
    assert verify_url("IGI", "710597072") == "https://www.igi.org/verify-your-report/?r=710597072"
    assert verify_url("HRD", "123") is None and verify_url("GIA", "") is None
    data, _ = build_workbook([dict(fields("gia_natural.txt"), source_file="a.pdf")])
    cert = load_workbook(io.BytesIO(data)).active["J2"]
    assert cert.value == "2215487963" and cert.hyperlink.target.endswith("reportno=2215487963")


def _text_pdf(lines):
    import pymupdf
    doc = pymupdf.open(); page = doc.new_page()
    for i, line in enumerate(lines):
        page.insert_text((40, 60 + 16 * i), line, fontsize=10)
    return doc.tobytes()


def test_digital_pdf_read_from_text_layer_without_ocr(monkeypatch):
    def no_ocr(*a, **k):
        raise AssertionError("OCR must not run for a digital PDF")
    monkeypatch.setattr(ocr, "active_backend", no_ocr)
    monkeypatch.setattr(ocr, "run_unlimited", no_ocr)
    pdf = _text_pdf(["GIA NATURAL DIAMOND GRADING REPORT", "February 24, 2025",
                     "GIA Report Number ........................ 1234567890",
                     "Shape and Cutting Style .................. Round Brilliant",
                     "Measurements .............................. 5.41 - 5.45 x 3.13 mm",
                     "Carat Weight .............................. 0.55 carat",
                     "Color Grade ............................... E",
                     "Clarity Grade ............................. VVS1",
                     "Cut Grade ................................. Excellent",
                     "Polish .................................... Excellent",
                     "Symmetry .................................. Excellent",
                     "Fluorescence .............................. None"])
    r = format_record(dict(extract_fields(ocr.run_ocr("gia.pdf", pdf, engine="paddle")[1])))
    assert [r[k] for k in ("shape", "carat", "color", "clarity", "cut", "polish", "symmetry", "fluorescence",
                           "lab", "report_number", "report_date")] == \
        ["Round", 0.55, "E", "VVS1", "EX", "EX", "EX", "NON", "GIA", "1234567890", "2025-02-24"]


def test_scanned_pdf_still_goes_to_ocr(monkeypatch):
    import pymupdf
    doc = pymupdf.open(); page = doc.new_page()
    page.insert_image(page.rect, stream=_png(600, 800))   # image only, no text layer
    called = []
    monkeypatch.setattr(ocr, "active_backend", lambda: "unlimited")
    monkeypatch.setattr(ocr, "run_unlimited", lambda f, d: called.append(f) or ("x", "x"))
    ocr.run_ocr("scan.pdf", doc.tobytes())
    assert called == ["scan.pdf"]


@pytest.mark.parametrize("gia,trade", [   # Rapaport Trade's "GIA shapes and trade shapes" table
    ("Rectangular Modified Brilliant", "Radiant"), ("Cut-Cornered Square Modified Brilliant", "Square Radiant"),
    ("Modified Square Brilliant", "Cushion Modified"), ("Square Modified Brilliant", "Princess"),
    ("Round-Cornered Rectangular Modified Brilliant", "Other"), ("Modified Rectangular Brilliant", "Other"),
    ("Cushion Brilliant", "Cushion Brilliant"), ("Trilliant", "Trilliant"), ("Old European Brilliant", "European Cut")])
def test_rapaport_shapes(gia, trade):
    assert format_record({"shape": gia})["shape"] == trade


def test_fancy_colour_and_fluorescence_colour_split():
    r = format_record({"color": "Fancy Light Brownish-Yellow", "fluorescence": "Medium Blue"})
    assert (r["fancy_intensity"], r["fancy_overtone"], r["fancy_color"]) == ("Fancy Light", "Brownish", "Yellow")
    assert (r["fluorescence"], r["fluor_color"]) == ("MED", "B")
    r = format_record({"color": "E", "fluorescence": "None"})
    assert r.get("fancy_color") is None and (r["fluorescence"], r["fluor_color"]) == ("NON", "N")


def test_igi_crown_and_pavilion_pairs():
    r = extract_fields("Crown Height - Angle | 17.5% - 37.8°\nPavilion Depth - Angle | 45% - 42")
    assert (r["crown_height"], r["crown_angle"], r["pavilion_depth"], r["pavilion_angle"]) == (17.5, 37.8, 45, 42)
    r = extract_fields("Crown Height | 14.5%\nPavilion Depth | 43%")   # IGI online summary
    assert (r["crown_height"], r["pavilion_depth"]) == (14.5, 43)


def test_append_understands_rapaport_column_names():
    wb = Workbook(); s = wb.active
    s.append(["StockNo", "Shp", "Sz", "Colr", "Clar", "CutGrade", "Finish", "Sym", "FluorIntensity", "FlrColor",
              "Laboratory", "CertNum", "Dpth", "Tbl"])
    buf = io.BytesIO(); wb.save(buf)
    data, info = build_workbook([dict(fields("gia_natural.txt"), source_file="a.pdf")], buf.getvalue())
    ws = load_workbook(io.BytesIO(data)).active
    assert [c.value for c in ws[2]][:14] == [None, "Round", 1.01, "G", "VS1", "EX", "EX", "VG", "FNT", None,
                                            "GIA", "2215487963", 61.6, 57]


@pytest.mark.parametrize("text,flt,colour", [("MediumBlue", "MED", "B"), ("Slight (Green)", "SL", "G"),
                                             ("Medum Blue", "MED", "B"), ("Very Slight", "VSL", None),
                                             ("None", "NON", "N")])
def test_fluorescence_with_colour(text, flt, colour):
    r = format_record(dict(extract_fields(f"Fluorescence | {text}")))
    assert (r["fluorescence"], r.get("fluor_color")) == (flt, colour)


def test_misread_crown_height_label():
    assert extract_fields("Crown Helght | 18%")["crown_height"] == 18


@pytest.mark.parametrize("text,grade", [
    ("Clarity Grade | Flawless", "FL"), ("Clarity Grade ...... FLAWLESS", "FL"), ("Clarity Grade | Flawles", "FL"),
    ("Clarity Grade | Internally Flawless", "IF"), ("Clarity Grade | Internaly Flawles", "IF"),
    ("Clarity Grade | VS1\nCLARITY GRADE: | Internally Flawless | VVS1 | VVS2", "VS1"),
    ("CLARITY GRADE: | Internally Flawless | VVS1 | VVS2 | VS1 | VS2", None),   # only the printed scale
])
def test_clarity_words_and_printed_scales(text, grade):
    assert extract_fields(text)["clarity"] == grade


def test_colour_scale_is_not_a_grade():
    assert extract_fields("COLOR GRADE: | D | E | F | G | H")["color"] is None
    assert extract_fields("Color Grade | G\nCOLOR GRADE: D E F G H I J")["color"] == "G"

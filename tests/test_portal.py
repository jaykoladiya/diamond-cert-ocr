import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from app import ocr
from app.excel import build_workbook
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
    assert info["mode"] == "new" and ws["B2"].value == "2215487963" and ws.cell(1, 1).value == "Lab"

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


def _png():
    from PIL import Image
    b = io.BytesIO(); Image.new("RGB", (40, 40), "white").save(b, "PNG"); return b.getvalue()


def test_api_extract_and_export(client):
    r = client.post("/api/extract", files=[("files", ("cert.png", _png(), "image/png")),
                                           ("files", ("notes.txt", b"x", "text/plain"))]).json()
    ok, bad = r["results"]
    assert ok["record"]["report_number"] == "LG612345678" and ok["missing"] == []
    assert "Unsupported" in bad["error"]
    resp = client.post("/api/export", data={"records": json.dumps([ok["record"]])})
    assert resp.status_code == 200
    ws = load_workbook(io.BytesIO(resp.content)).active
    assert ws["B2"].value == "LG612345678"


def test_pdf_pages():
    import pymupdf as fitz
    doc = fitz.open(); doc.new_page(); doc.new_page()
    pages = ocr.to_page_images("x.pdf", doc.tobytes())
    assert len(pages) == 2 and pages[0][0] == "image/png"

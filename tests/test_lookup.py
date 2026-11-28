"""GIA report lookup by number (report PDF -> text layer). Downloads are faked: tests never
contact the report service."""
import pytest
from fastapi.testclient import TestClient

from app import lookup
from app.main import app


def _report_pdf(number, color="E"):
    import pymupdf
    doc = pymupdf.open(); page = doc.new_page()
    lines = ["GIA NATURAL DIAMOND GRADING REPORT", "February 24, 2025",
             f"GIA Report Number ............ {number}", "Shape and Cutting Style ...... Round Brilliant",
             "Measurements ................. 5.41 - 5.45 x 3.13 mm", "Carat Weight ................. 0.55 carat",
             f"Color Grade .................. {color}", "Clarity Grade ................ VVS1",
             "Cut Grade .................... Excellent", "Polish ....................... Excellent",
             "Symmetry ..................... Very Good", "Fluorescence ................. Faint"]
    for i, line in enumerate(lines):
        page.insert_text((40, 60 + 16 * i), line, fontsize=10)
    return doc.tobytes()


class _Resp:
    def __init__(self, content, status=200):
        self.content, self.status_code = content, status


@pytest.fixture
def svc(monkeypatch, tmp_path):
    calls = []

    def get(url, timeout, headers):
        calls.append(url)
        number = url.rsplit("=", 1)[1]
        if number == "1111111111":
            return _Resp(b"<html>not found</html>")
        if number == "2222222222":
            return _Resp(_report_pdf("9999999999"))  # someone else's report
        return _Resp(_report_pdf(number))

    monkeypatch.setattr(lookup.requests, "get", get)
    monkeypatch.setattr(lookup, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(lookup, "PAUSE_SECONDS", 0)
    monkeypatch.setattr(lookup, "SETTINGS_FILE", tmp_path / "local_settings.json")
    monkeypatch.setenv("REPORT_PDF_URL", "https://reports.example/pdf?reportno={report}")
    return calls


def test_numbers_picked_from_pasted_text():
    text = """2517492150
    4.00W908211  BR 4.022 F VVS2  GIA 6237628416  https://x/y?reportno=2186456607
    2517492150, 1.01 carat"""
    assert lookup.parse_numbers(text) == ["2517492150", "6237628416", "2186456607"]


def test_lookup_fills_row_and_downloads_once(svc):
    c = TestClient(app)
    r = c.post("/api/lookup", data={"numbers": "2517492150\n6237628416"}).json()["results"]
    assert [x["record"]["report_number"] for x in r] == ["2517492150", "6237628416"]
    rec = r[0]["record"]
    assert [rec[k] for k in ("shape", "carat", "color", "clarity", "cut", "polish", "symmetry", "fluorescence",
                             "lab", "report_date")] == \
        ["Round", 0.55, "E", "VVS1", "EX", "EX", "VG", "FNT", "GIA", "2025-02-24"]
    assert r[0]["missing"] == [] and r[0]["pdf"] == "/api/report/2517492150.pdf"
    assert c.get("/api/report/2517492150.pdf").content.startswith(b"%PDF")
    c.post("/api/lookup", data={"numbers": "2517492150"})
    assert svc == ["https://reports.example/pdf?reportno=2517492150",
                   "https://reports.example/pdf?reportno=6237628416"]      # cached: not fetched again


def test_lookup_errors_are_per_number(svc):
    r = TestClient(app).post("/api/lookup", data={"numbers": "1111111111 2222222222 2517492150"}).json()["results"]
    assert "no report PDF" in r[0]["error"]
    assert "different report" in r[1]["error"]
    assert r[2]["record"]["color"] == "E"


def test_lookup_can_be_turned_off(svc, monkeypatch):
    monkeypatch.setenv("REPORT_PDF_URL", "off")
    r = TestClient(app).post("/api/lookup", data={"numbers": "2517492150"}).json()["results"]
    assert "No report link set" in r[0]["error"] and svc == []


def test_no_link_built_in(monkeypatch, tmp_path):
    monkeypatch.delenv("REPORT_PDF_URL", raising=False)
    monkeypatch.setattr(lookup, "SETTINGS_FILE", tmp_path / "local_settings.json")
    assert lookup.link_template() == "" and not lookup.enabled()


def test_link_pasted_in_settings(svc, monkeypatch, tmp_path):
    monkeypatch.delenv("REPORT_PDF_URL", raising=False)
    c = TestClient(app)
    assert c.get("/api/settings").json()["report_pdf_url"] == ""
    r = c.post("/api/settings", data={"report_pdf_url": "https://supplier.example/Show/Index?reportno=2517492150"})
    assert r.json()["report_pdf_url"] == "https://supplier.example/Show/Index?reportno={report}"
    assert (tmp_path / "local_settings.json").exists()
    c.post("/api/lookup", data={"numbers": "6237628416"})
    assert svc == ["https://supplier.example/Show/Index?reportno=6237628416"]
    assert c.post("/api/settings", data={"report_pdf_url": "not a link"}).status_code == 400
    assert c.post("/api/settings", data={"report_pdf_url": "https://x.example/no-number"}).status_code == 400
    assert c.post("/api/settings", data={"report_pdf_url": ""}).json()["report_pdf_url"] == ""
    assert not lookup.enabled()


def test_no_numbers_is_a_clear_error(svc):
    r = TestClient(app).post("/api/lookup", data={"numbers": "Round 1.01 E VS1"})
    assert r.status_code == 400 and "10 digits" in r.json()["detail"]

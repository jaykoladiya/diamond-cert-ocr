"""Windows OCR engine (Windows.Media.Ocr, as in PowerToys Text Extractor), tested through a
fake PyWinRT that mirrors the real API."""
import io
import subprocess
import sys
from pathlib import Path

import pytest

from app import ocr, ocr_windows as Wn
from app.extract import extract_fields

from . import fake_winrt

HERE = Path(__file__).parent


@pytest.fixture
def fresh(monkeypatch):
    monkeypatch.setattr(Wn, "_state", {"engine": None, "error": None, "checked": False})
    monkeypatch.setattr(Wn.sys, "platform", "win32")


def _png(w=800, h=200):
    from PIL import Image
    b = io.BytesIO(); Image.new("RGB", (w, h), "white").save(b, "PNG")
    return b.getvalue()


def test_words_become_lines_with_page_coordinates(monkeypatch, fresh):
    seen = []

    def reader(img):  # the fake engine sees the upscaled page; answer in its coordinates
        seen.append(img.shape)
        f = img.shape[1] / 800
        return [(t, (x * f, 20 * f, w * f, 18 * f)) for t, x, w in
                [("Color", 20, 60), ("Grade", 85, 60), ("..........", 150, 300), ("G", 520, 14)]]

    calls = fake_winrt.install(monkeypatch, reader)
    assert Wn.available()
    text = ocr.run_ocr("cert.png", _png(), engine="windows")[1]
    assert extract_fields(text)["color"] == "G"
    assert seen[0][1] == 2400                        # small page enlarged, then upscaled for Windows OCR
    assert calls["closed"] == len(calls["bitmaps"])  # every SoftwareBitmap is closed


def test_missing_language_pack_is_explained(monkeypatch, fresh):
    fake_winrt.install(monkeypatch, lambda img: [], languages=())
    assert not Wn.available()
    assert "Optical character recognition" in Wn.unavailable_reason()
    with pytest.raises(ocr.OCRError, match="Optical character recognition"):
        ocr.run_ocr("c.png", _png(), engine="windows")


def test_falls_back_to_any_english_recognizer(monkeypatch, fresh):
    fake_winrt.install(monkeypatch, lambda img: [], languages=("en-GB",))
    assert Wn.available()


def test_not_offered_off_windows(monkeypatch):
    monkeypatch.setattr(Wn, "_state", {"engine": None, "error": None, "checked": False})
    monkeypatch.setattr(Wn.sys, "platform", "linux")
    assert not Wn.available()


def test_auto_prefers_windows_over_paddle(monkeypatch):
    monkeypatch.setattr(ocr, "OCR_BACKEND", "auto")
    monkeypatch.setattr(ocr, "unlimited_online", lambda: False)
    monkeypatch.setattr(Wn, "available", lambda: True)
    monkeypatch.setattr(ocr.ocr_paddle, "available", lambda: True)
    assert ocr.active_backend() == "windows"
    st = ocr.server_status()
    assert st["backend"] == "windows" and [e["key"] for e in st["engines"]] == ["unlimited", "windows", "paddle"]


@pytest.mark.parametrize("rot,noise", [(-2.5, 7), (1.5, 10)])
def test_windows_path_end_to_end(monkeypatch, fresh, tmp_path, rot, noise):
    """Full Windows-engine path on a generated phone-photo certificate, with PP-OCR (RapidOCR)
    answering inside the fake engine at word level."""
    rapid = pytest.importorskip("rapidocr_onnxruntime")
    eng = rapid.RapidOCR()

    def reader(img):
        if img.shape[0] < 200:
            # second-read strips hold one line. RapidOCR's *detector* cannot find a lone letter
            # (the "D"), so read the strip as a line with its recogniser, as a line reader would.
            out, _ = eng.text_recognizer([img])
            text = out[0][0].strip()
            return [(text, (0, 0, img.shape[1], img.shape[0]))] if text else []
        res, _ = eng(img)
        words = []
        for box, text, _score in res or []:
            x1, y1 = min(p[0] for p in box), min(p[1] for p in box)
            x2, y2 = max(p[0] for p in box), max(p[1] for p in box)
            parts = text.split()  # Windows reports words; split boxes proportionally
            total = max(1, sum(len(p) for p in parts) + len(parts) - 1)
            x = x1
            for p in parts:
                w = (x2 - x1) * len(p) / total
                words.append((p, (x, y1, w, y2 - y1)))
                x += w + (x2 - x1) / total
        return words

    fake_winrt.install(monkeypatch, reader)
    img = tmp_path / "c.jpg"
    subprocess.run([sys.executable, str(HERE / "make_photo_cert.py"), str(img), str(rot), str(noise)], check=True)
    r = extract_fields(ocr.run_ocr("c.jpg", img.read_bytes(), engine="windows")[1])
    expect = {"report_number": "2181993704", "report_date": "2018-01-08", "shape": "Round Brilliant",
              "carat": 2.01, "color": "D", "clarity": "VVS1", "cut": "Excellent", "polish": "Excellent",
              "symmetry": "Excellent", "fluorescence": "None"}
    assert {k: r[k] for k in expect} == expect

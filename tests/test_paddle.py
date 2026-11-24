"""PaddleOCR path. The engine itself needs model downloads, so these tests cover the layout
and repair logic; test_pipeline_end_to_end runs the full path with PP-OCR models through
RapidOCR (same PaddleOCR models, ONNX build) when that package is installed."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app import ocr, ocr_paddle as P
from app.extract import extract_fields, ocr_fix

HERE = Path(__file__).parent


def test_two_column_lines_from_real_ppocr_boxes():
    boxes = [(*b["box"], b["text"], b["score"]) for b in json.loads((HERE / "fixtures/ppocr_gia_boxes.json").read_text())]
    text = P.lines_to_text(P.group_lines(boxes))
    assert "Carat Weight | 1.71 carat" in text          # value sits 5px higher than its label
    assert "GIA Report Number | 6452198730" in text
    r = extract_fields(text)
    assert (r["report_number"], r["carat"], r["clarity"]) == ("6452198730", 1.71, "SI2")  # "S12" repaired
    assert (r["table_pct"], r["depth_pct"], r["girdle"]) == (62, 67.3, "Thin to Medium")
    assert r["inscription"] == "GIA 6452198730"         # "GlA" repaired


@pytest.mark.parametrize("raw,fixed", [("S12", "SI2"), ("WS1", "VVS1"), ("VVSI", "VVS1"), ("1F", "IF"),
                                       ("VS 2", "VS2"), ("SI1", "SI1")])
def test_clarity_ocr_fixes(raw, fixed):
    assert ocr_fix("clarity", raw) == fixed


def test_grade_fuzzy():
    assert ocr_fix("polish", "Excelent") == "excellent"
    assert ocr_fix("symmetry", "pood") == "pood"         # good/poor tie: leave for a human


def test_backend_selection(monkeypatch):
    monkeypatch.setattr(ocr, "OCR_BACKEND", "auto")
    monkeypatch.setattr(ocr, "unlimited_online", lambda: False)
    monkeypatch.setattr(P, "available", lambda: True)
    assert ocr.active_backend() == "paddle"
    monkeypatch.setattr(P, "run", lambda pages: "GIA Report Number ..... 1234567890\nColor Grade ..... F")
    from PIL import Image
    import io
    b = io.BytesIO(); Image.new("RGB", (10, 10)).save(b, "PNG")
    raw, text = ocr.run_ocr("c.png", b.getvalue())
    assert extract_fields(text)["color"] == "F"
    monkeypatch.setattr(ocr, "unlimited_online", lambda: True)
    assert ocr.active_backend() == "unlimited"


@pytest.mark.parametrize("rot,noise", [(-3, 7), (0, 10), (2.5, 12)])
def test_pipeline_end_to_end(tmp_path, rot, noise):
    rapid = pytest.importorskip("rapidocr_onnxruntime")
    import cv2
    img_path = tmp_path / "c.jpg"
    subprocess.run([sys.executable, str(HERE / "make_photo_cert.py"), str(img_path), str(rot), str(noise)], check=True)
    eng = rapid.RapidOCR()
    img = P.deskew(cv2.imread(str(img_path)))
    H, W = img.shape[:2]
    res, _ = eng(img)
    items = [(min(p[0] for p in b), min(p[1] for p in b), max(p[0] for p in b), max(p[1] for p in b), t, float(s))
             for b, t, s in res]
    lines = P.group_lines(items)
    crop = lambda x1, y1, x2, y2: img[max(0, int(y1)):min(H, int(y2)), max(0, int(x1)):min(W, int(x2))]

    def rec(c):
        out, _ = eng.text_recognizer([c])
        return out[0][0], float(out[0][1])

    P.fill_missing_values(lines, W, rec, crop)
    r = extract_fields(P.lines_to_text(lines))
    expect = {"report_number": "2181993704", "report_date": "2018-01-08", "shape": "Round Brilliant",
              "carat": 2.01, "color": "D", "clarity": "VVS1", "cut": "Excellent", "polish": "Excellent",
              "symmetry": "Excellent", "fluorescence": "None", "length_mm": 8.18, "depth_mm": 4.93}
    assert {k: r[k] for k in expect} == expect


class _FakePaddle:
    """Stand-in for the paddleocr module: records constructor options and can fail like
    PaddlePaddle 3.3 on Windows does with oneDNN enabled."""
    ERR = ("(Unimplemented) ConvertPirAttribute2RuntimeAttribute not support "
           "[pir::ArrayAttribute<pir::DoubleAttribute>] (at ..\\paddle\\fluid\\framework\\new_executor"
           "\\instruction\\onednn\\onednn_instruction.cc:118)")

    def __init__(self):
        self.made = []
        outer = self

        class PaddleOCR:
            def __init__(self, **kw):
                outer.made.append(kw)
                self.kw = kw

            def predict(self, img):
                if self.kw.get("enable_mkldnn"):
                    raise NotImplementedError(outer.ERR)
                return [{"rec_boxes": [[10, 10, 120, 30], [300, 10, 330, 30]],
                         "rec_texts": ["Color Grade", "G"], "rec_scores": [0.95, 0.95]}]

        class TextRecognition:
            def __init__(self, **kw):
                self.kw = kw

            def predict(self, input):
                return [{"rec_text": "", "rec_score": 0.0}]

        self.PaddleOCR, self.TextRecognition = PaddleOCR, TextRecognition


def _png_page():
    from PIL import Image
    import io
    b = io.BytesIO(); Image.new("RGB", (400, 60), "white").save(b, "PNG")
    return [("image/png", b.getvalue())]


def test_paddle_cpu_without_onednn_by_default(monkeypatch):
    fake = _FakePaddle()
    monkeypatch.setitem(sys.modules, "paddleocr", fake)
    monkeypatch.setattr(P, "_engine", None)
    monkeypatch.setattr(P, "_mkldnn", P.USE_MKLDNN)
    assert "Color Grade | G" in P.run(_png_page())
    assert fake.made[0]["enable_mkldnn"] is False and fake.made[0]["device"] == "cpu"


def test_paddle_onednn_error_falls_back(monkeypatch):
    fake = _FakePaddle()
    monkeypatch.setitem(sys.modules, "paddleocr", fake)
    monkeypatch.setattr(P, "_engine", None)
    monkeypatch.setattr(P, "_mkldnn", True)          # as with PADDLE_MKLDNN=1
    assert "Color Grade | G" in P.run(_png_page())   # first attempt hits the error, retry works
    assert [m["enable_mkldnn"] for m in fake.made] == [True, False]
    assert P._mkldnn is False

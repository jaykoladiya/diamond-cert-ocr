"""OCR backends: an Unlimited-OCR-2 server (SGLang, GPU) or local PaddleOCR (CPU).

OCR_BACKEND=auto (default) uses the Unlimited-OCR-2 server when it answers, else the
OCR built into Windows (as in PowerToys Text Extractor), else PaddleOCR.

For Unlimited-OCR-2: turns an uploaded certificate (PDF or image) into page images, sends them to the
server in one request (as in the upstream README), and converts the raw layout
output into Markdown with the upstream post-processor.
"""
import base64
import io
import json
import os
import re
import time

import requests

from . import ocr_paddle, ocr_windows
from .vendor.process_unlimitedOCR2 import convert

OCR_BACKEND = os.environ.get("OCR_BACKEND", "auto").lower()  # auto | unlimited | windows | paddle
ENGINE_LABELS = {"unlimited": "Unlimited-OCR-2 (GPU server)", "windows": "Windows OCR (built in)",
                 "paddle": "PaddleOCR (local CPU)"}

OCR_URL = os.environ.get("OCR_URL", "http://127.0.0.1:10000").rstrip("/")
OCR_MODEL = os.environ.get("OCR_MODEL", "Unlimited-OCR-2")
OCR_TIMEOUT = int(os.environ.get("OCR_TIMEOUT", "600"))
TOKENS_PER_PAGE = int(os.environ.get("OCR_TOKENS_PER_PAGE", "8000"))
PDF_DPI = int(os.environ.get("OCR_PDF_DPI", "300"))
MAX_PAGES = int(os.environ.get("OCR_MAX_PAGES", "4"))  # certificates are 1-2 pages

try:  # the n-gram repetition guard ships with the custom SGLang wheel; optional here
    from sglang.srt.sampling.custom_logit_processor import DeepseekOCRNoRepeatNGramLogitProcessor
    NGRAM_PROCESSOR = DeepseekOCRNoRepeatNGramLogitProcessor.to_str()
except Exception:  # noqa: BLE001
    NGRAM_PROCESSOR = None

IMAGE_EXT = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
             ".webp": "image/webp", ".bmp": "image/bmp", ".tif": "image/tiff", ".tiff": "image/tiff"}


class OCRError(RuntimeError):
    pass


def to_page_images(filename, data, dpi=None):
    """Return a list of (mime, bytes) page images for a PDF or image upload."""
    ext = os.path.splitext(filename.lower())[1]
    if ext == ".pdf":
        try:
            import pymupdf as fitz
        except ImportError:  # older PyMuPDF
            import fitz

        doc = fitz.open(stream=data, filetype="pdf")
        dpi = dpi or PDF_DPI
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pages = [("image/png", page.get_pixmap(matrix=mat).tobytes("png"))
                 for i, page in enumerate(doc) if i < MAX_PAGES]
        doc.close()
        return pages
    if ext in (".tif", ".tiff", ".bmp", ".webp"):
        from PIL import Image  # normalise formats the server may not decode

        img = Image.open(io.BytesIO(data)).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return [("image/png", buf.getvalue())]
    if ext in IMAGE_EXT:
        return [(IMAGE_EXT[ext], data)]
    raise OCRError(f"Unsupported file type: {ext or filename}")


def build_payload(pages, crop_mode=True):
    content = [{"type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{base64.b64encode(b).decode()}"}}
               for mime, b in pages]
    content.append({"type": "text", "text": "<PAGE><image>" * len(pages) + "Multi page parsing."})
    payload = {
        "model": OCR_MODEL,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": TOKENS_PER_PAGE * len(pages),
        "temperature": 0,
        "skip_special_tokens": False,
        "images_config": {"crop_mode": crop_mode},  # True = gundam (tiles): best for small print
    }
    if NGRAM_PROCESSOR:
        payload["custom_logit_processor"] = NGRAM_PROCESSOR
        payload["custom_params"] = {
            "ngram_size": 35,
            "window_size": 1024 if len(pages) > 1 else 128,
            "page_token_id": 128827,
            "eos_token_id": 1,
            "max_page_tokens": 20000,
        }
    return payload


def pdf_text(data):
    """Text layer of a digital PDF (GIA/IGI download their reports with one), in reading
    order, or None for scans/photos saved as PDF. Exact characters: no OCR needed."""
    try:
        import pymupdf as fitz
    except ImportError:  # older PyMuPDF
        import fitz
    from .extract import KEY_FIELDS, extract_fields
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception:  # noqa: BLE001 - not a readable PDF: let OCR report it
        return None
    text = "\n".join(page.get_text("text") for i, page in enumerate(doc) if i < MAX_PAGES)
    doc.close()
    # GIA background microprint: "GEMOLOGICAL INSTITUTE OF AMERICA" repeated across the page
    text = re.sub(r"(?:GE\s?MOLOGICAL\s+INSTITUTE\s+OF\s+AME\s?RICA\s*){2,}", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    found = extract_fields(text)
    # use it only if it really carries the grading (not just a scanned image with a caption)
    return text if sum(found[k] not in (None, "") for k in KEY_FIELDS) >= 3 else None


def run_ocr(filename, data, engine=None):
    """OCR one uploaded file. `engine` picks one explicitly ("unlimited", "windows",
    "paddle"); otherwise the active backend is used. A digital PDF is read from its text
    layer instead, whatever the engine. Returns (raw_output, text)."""
    if filename.lower().endswith(".pdf") and os.environ.get("PDF_TEXT", "1") != "0":
        text = pdf_text(data)
        if text:
            return text, text
    backend = engine if engine and engine != "auto" else active_backend()
    if backend in ("windows", "paddle"):
        mod = ocr_windows if backend == "windows" else ocr_paddle
        if not mod.available():
            raise OCRError(f"{ENGINE_LABELS[backend]} is not available"
                           + (f": {ocr_windows.unavailable_reason()}" if backend == "windows" else ""))
        pages = to_page_images(filename, data, dpi=ocr_paddle.PDF_DPI)
        if not pages:
            raise OCRError("No pages found in file")
        text = mod.run(pages)
        return text, text
    if backend == "unlimited":
        return run_unlimited(filename, data)
    if backend is None:
        raise OCRError("No OCR engine available: the Unlimited-OCR server at " + OCR_URL + " is offline, "
                       "Windows OCR is unavailable and PaddleOCR is not installed")
    raise OCRError(f"Unknown OCR engine: {backend}")


def run_unlimited(filename, data):
    pages = to_page_images(filename, data)
    if not pages:
        raise OCRError("No pages found in file")
    session = requests.Session()
    session.trust_env = False  # the OCR server is usually local; don't route via proxies
    try:
        resp = session.post(f"{OCR_URL}/v1/chat/completions",
                            data=json.dumps(build_payload(pages)),
                            headers={"Content-Type": "application/json"},
                            timeout=OCR_TIMEOUT)
    except requests.RequestException as e:
        raise OCRError(f"Cannot reach OCR server at {OCR_URL}: {e}") from e
    if resp.status_code != 200:
        raise OCRError(f"OCR server returned HTTP {resp.status_code}: {resp.text[:300]}")
    raw = resp.json()["choices"][0]["message"].get("content") or ""
    return raw, convert(raw)


_probe = {"t": 0.0, "ok": False}


def unlimited_online(max_age=30):
    if time.time() - _probe["t"] > max_age:
        try:
            r = requests.get(f"{OCR_URL}/v1/models", timeout=3, proxies={"http": None, "https": None})
            _probe["ok"] = r.status_code == 200
        except requests.RequestException:
            _probe["ok"] = False
        _probe["t"] = time.time()
    return _probe["ok"]


def engine_available(name):
    if name == "unlimited":
        return unlimited_online()
    if name == "windows":
        return ocr_windows.available()
    if name == "paddle":
        return ocr_paddle.available()
    return False


def active_backend():
    if OCR_BACKEND in ENGINE_LABELS:
        return OCR_BACKEND if OCR_BACKEND == "unlimited" or engine_available(OCR_BACKEND) else None
    for name in ("unlimited", "windows", "paddle"):
        if engine_available(name):
            return name
    return None


def server_status():
    backend = active_backend()
    engines = [{"key": k, "label": v, "available": engine_available(k)} for k, v in ENGINE_LABELS.items()]
    label = ENGINE_LABELS.get(backend, "No OCR engine available")
    if backend == "unlimited":
        label += f" at {OCR_URL}"
    from . import lookup
    return {"ok": backend is not None, "backend": backend, "label": label, "engines": engines,
            "lookup": lookup.enabled()}

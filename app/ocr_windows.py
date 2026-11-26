"""Windows' built-in OCR (Windows.Media.Ocr): the engine PowerToys Text Extractor uses.

No model download and no GPU: it ships with Windows 10/11. Called through Microsoft's
PyWinRT packages (winrt-Windows.Media.Ocr ...). Images are upscaled like PowerToys does
(small text reads better), and the same page pipeline as PaddleOCR is used: deskew,
line building, second read of missing values.
"""
import os
import sys
import threading

LANG = os.environ.get("WINDOWS_OCR_LANG", "en-US")
TARGET_LONG_SIDE = int(os.environ.get("WINDOWS_OCR_TARGET_PX", "2400"))  # upscale pages to about this
SCORE = 0.9  # Windows OCR reports no confidence; treat readings as fairly sure

_lock = threading.Lock()
_run_lock = threading.Lock()
_tls = threading.local()
_state = {"engine": None, "error": None, "checked": False}


def _thread_init():
    """COM apartment per worker thread (pywinrt only sets one up for the importing thread)."""
    if getattr(_tls, "ready", False):
        return
    try:
        from winrt import _winrt
        _winrt.init_apartment(_winrt.MTA)
    except Exception:  # noqa: BLE001 - already initialised on this thread
        pass
    _tls.ready = True


def _create_engine():
    from winrt.windows.globalization import Language
    from winrt.windows.media.ocr import OcrEngine

    engine = OcrEngine.try_create_from_language(Language(LANG))
    if engine is None:  # requested language not installed: any English recogniser, then profile
        for lang in OcrEngine.available_recognizer_languages:
            if lang.language_tag.lower().startswith("en"):
                engine = OcrEngine.try_create_from_language(lang)
                break
    if engine is None:
        engine = OcrEngine.try_create_from_user_profile_languages()
    return engine


def _engine():
    with _lock:
        if not _state["checked"]:
            _state["checked"] = True
            try:
                _thread_init()
                _state["engine"] = _create_engine()
                if _state["engine"] is None:
                    _state["error"] = ("Windows has no OCR language installed. Settings > Time & language > "
                                       "Language & region > English > Language options > add 'Optical "
                                       "character recognition'.")
            except ImportError:
                _state["error"] = "PyWinRT is not installed (pip install -r requirements.txt)"
            except Exception as e:  # noqa: BLE001
                _state["error"] = f"Windows OCR unavailable: {e}"
        return _state["engine"]


def available():
    return sys.platform == "win32" and _engine() is not None


def unavailable_reason():
    if sys.platform != "win32":
        return "Windows OCR only runs on Windows"
    _engine()
    return _state["error"]


def _ocr_lines(img):
    """Run Windows OCR on a BGR numpy image; return its OcrLine objects."""
    import cv2
    import numpy as np
    from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap
    from winrt.windows.media.ocr import OcrEngine

    _thread_init()
    engine = _engine()
    limit = int(OcrEngine.max_image_dimension)
    h, w = img.shape[:2]
    if max(h, w) > limit:
        s = limit / max(h, w)
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
        h, w = img.shape[:2]
    bgra = np.ascontiguousarray(cv2.cvtColor(img, cv2.COLOR_BGR2BGRA))
    bitmap = SoftwareBitmap.create_copy_from_buffer(
        bgra, BitmapPixelFormat.BGRA8, w, h, BitmapAlphaMode.PREMULTIPLIED)
    try:
        return list(engine.recognize_async(bitmap).get().lines)
    finally:
        bitmap.close()


def _upscale(img, factor):
    import cv2
    return cv2.resize(img, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC) if factor > 1.01 else img


def detect(img):
    """Word boxes [(x1, y1, x2, y2, text, score)] in the coordinates of `img`."""
    h, w = img.shape[:2]
    factor = min(2.5, max(1.0, TARGET_LONG_SIDE / max(h, w)))
    items = []
    for line in _ocr_lines(_upscale(img, factor)):
        for word in line.words:
            r = word.bounding_rect
            items.append((r.x / factor, r.y / factor, (r.x + r.width) / factor,
                          (r.y + r.height) / factor, word.text, SCORE))
    return items


def recognize(img):
    """Text of a small strip (label + value) for the second read."""
    import cv2
    h = img.shape[0]
    strip = _upscale(img, min(4.0, max(1.0, 64 / max(1, h))))
    strip = cv2.copyMakeBorder(strip, 24, 24, 24, 24, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    text = " ".join(line.text for line in _ocr_lines(strip))
    return text, SCORE if text else 0.0


def run(pages):
    from .ocr_paddle import process_pages
    if _engine() is None:
        raise RuntimeError(unavailable_reason())
    with _run_lock:  # one certificate at a time through the OCR engine
        return process_pages(pages, detect, recognize)

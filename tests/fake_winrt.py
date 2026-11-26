"""A stand-in for Microsoft's PyWinRT packages, mirroring the API used by app/ocr_windows.py
(as declared in the winrt-Windows.Media.Ocr / Graphics.Imaging stubs), so the Windows OCR
engine can be tested off Windows. `reader(bgr_image) -> [(text, (x, y, w, h))]` plays the
role of the OCR engine, one entry per word."""
import sys
import types
from enum import IntEnum

import numpy as np


def install(monkeypatch, reader, languages=("en-US",)):
    calls = {"bitmaps": [], "closed": 0, "apartment": 0}

    class Language:
        def __init__(self, tag):
            self.language_tag = tag

    class Rect:
        def __init__(self, x, y, w, h):
            self.x, self.y, self.width, self.height = float(x), float(y), float(w), float(h)

    class Word:
        def __init__(self, text, rect):
            self.text, self.bounding_rect = text, Rect(*rect)

    class Line:
        def __init__(self, words):
            self.words = words
            self.text = " ".join(w.text for w in words)

    class Op:
        def __init__(self, result):
            self._r = result

        def get(self):
            return self._r

    class Engine:
        def recognize_async(self, bitmap):
            words = [Word(t, r) for t, r in reader(bitmap.bgr)]
            return Op(types.SimpleNamespace(lines=[Line(words)] if words else []))

    class OcrEngine:
        max_image_dimension = 10000
        available_recognizer_languages = [Language(t) for t in languages]

        @staticmethod
        def try_create_from_language(lang):
            return Engine() if lang.language_tag in languages else None

        @staticmethod
        def try_create_from_user_profile_languages():
            return Engine() if languages else None

    class BitmapPixelFormat(IntEnum):
        GRAY8 = 62
        BGRA8 = 87

    class BitmapAlphaMode(IntEnum):
        PREMULTIPLIED = 0
        IGNORE = 2

    class SoftwareBitmap:
        def __init__(self, bgr):
            self.bgr = bgr

        @staticmethod
        def create_copy_from_buffer(buf, fmt, w, h, alpha):
            assert fmt == BitmapPixelFormat.BGRA8
            a = np.frombuffer(memoryview(buf).tobytes(), np.uint8).reshape(h, w, 4)
            calls["bitmaps"].append((w, h))
            return SoftwareBitmap(np.ascontiguousarray(a[:, :, :3]))

        def close(self):
            calls["closed"] += 1

    def mod(name, **attrs):
        m = types.ModuleType(name)
        m.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, m)
        return m

    def init_apartment(kind):
        calls["apartment"] += 1

    winrt = mod("winrt")
    winrt._winrt = mod("winrt._winrt", init_apartment=init_apartment, MTA=0)
    mod("winrt.windows")
    mod("winrt.windows.globalization", Language=Language)
    mod("winrt.windows.media")
    mod("winrt.windows.media.ocr", OcrEngine=OcrEngine)
    mod("winrt.windows.graphics")
    mod("winrt.windows.graphics.imaging", SoftwareBitmap=SoftwareBitmap,
        BitmapPixelFormat=BitmapPixelFormat, BitmapAlphaMode=BitmapAlphaMode)
    return calls

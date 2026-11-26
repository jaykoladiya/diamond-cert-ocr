"""Local CPU OCR with PaddleOCR: for machines without a GPU that can run Unlimited-OCR-2.

PaddleOCR returns loose text boxes. We rebuild them into reading-order lines
("Label | Value | Label | Value" for two-column certificates) so the same field
extractor works for both backends. Labels left without a value on their line (e.g. a
single-letter colour grade the detector missed) get a second, recognition-only pass
over the area to the right of the label.
"""
import os
import re
import threading

from .extract import _LABEL_RES, _VALID_RES, _clean_value, ocr_fix

DET_MODEL = os.environ.get("PADDLE_DET_MODEL", "PP-OCRv5_server_det")  # most accurate on small text
REC_MODEL = os.environ.get("PADDLE_REC_MODEL", "en_PP-OCRv5_mobile_rec")
PDF_DPI = int(os.environ.get("PADDLE_PDF_DPI", "200"))
REREAD_BELOW = float(os.environ.get("PADDLE_REREAD_BELOW", "0.85"))  # re-read values less sure than this
# oneDNN (MKL-DNN) CPU acceleration. Off by default: PaddlePaddle 3.3 on Windows fails with
# "ConvertPirAttribute2RuntimeAttribute not support ..." in onednn_instruction.cc when it is on.
USE_MKLDNN = os.environ.get("PADDLE_MKLDNN", "0").lower() in ("1", "true", "yes")
_mkldnn = USE_MKLDNN

_lock = threading.Lock()
_engine = None  # (ocr, recognizer)


def available():
    try:
        import paddleocr  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def _load():
    global _engine
    if _engine is None:
        import paddleocr
        if hasattr(paddleocr, "TextRecognition"):  # PaddleOCR 3.x
            common = {"device": "cpu", "enable_mkldnn": _mkldnn}
            ocr = paddleocr.PaddleOCR(
                text_detection_model_name=DET_MODEL, text_recognition_model_name=REC_MODEL,
                use_doc_orientation_classify=False, use_doc_unwarping=False,
                use_textline_orientation=False, **common)
            rec = paddleocr.TextRecognition(model_name=REC_MODEL, **common)
            _engine = ("v3", ocr, rec)
        else:  # PaddleOCR 2.x
            ocr = paddleocr.PaddleOCR(lang="en", use_angle_cls=False, show_log=False)
            _engine = ("v2", ocr, None)
    return _engine


def _detect(img):
    """Return [(x1, y1, x2, y2, text, score)] for one BGR image."""
    ver, ocr, _ = _load()
    items = []
    if ver == "v3":
        import numpy as np
        for res in ocr.predict(img):
            boxes = np.asarray(res["rec_boxes"]).reshape(-1, 4).tolist()
            for box, text, score in zip(boxes, res["rec_texts"], res["rec_scores"]):
                items.append((*map(float, box), text, float(score)))
    else:
        for page in ocr.ocr(img, cls=False) or []:
            for poly, (text, score) in page or []:
                xs, ys = [p[0] for p in poly], [p[1] for p in poly]
                items.append((min(xs), min(ys), max(xs), max(ys), text, float(score)))
    return items


def _recognize(crop):
    ver, ocr, rec = _load()
    if ver == "v3":
        out = rec.predict(input=crop)
        return (out[0]["rec_text"], float(out[0]["rec_score"])) if out else ("", 0.0)
    res = ocr.ocr(crop, det=False, cls=False)
    return res[0][0] if res and res[0] else ("", 0.0)


# ── layout: boxes -> lines ───────────────────────────────────────────────────

def _v_overlap(a, b):
    inter = min(a[3], b[3]) - max(a[1], b[1])
    return inter / max(1.0, min(a[3] - a[1], b[3] - b[1]))


def group_lines(items):
    """Chain boxes into lines: from each unused box, repeatedly take the nearest box to
    the right (and then to the left) that overlaps the chain end by >=50% vertically.
    Returns lines as lists of boxes, top to bottom."""
    todo = sorted(items, key=lambda b: (b[1], b[0]))
    used, lines = set(), []

    def extend(line, rightward):
        while True:
            cur = line[-1] if rightward else line[0]
            cands = [(j, b) for j, b in enumerate(todo) if j not in used and _v_overlap(cur, b) >= 0.5
                     and (b[0] >= cur[2] - 5 if rightward else b[2] <= cur[0] + 5)]
            if not cands:
                return
            j, nxt = (min(cands, key=lambda jb: jb[1][0]) if rightward
                      else max(cands, key=lambda jb: jb[1][2]))
            used.add(j)
            if rightward:
                line.append(nxt)
            else:
                line.insert(0, nxt)

    for i, start in enumerate(todo):
        if i in used:
            continue
        used.add(i)
        line = [start]
        extend(line, True)
        extend(line, False)
        lines.append(line)
    lines.sort(key=lambda ln: (min(b[1] for b in ln), ln[0][0]))
    return lines


def _bare_label_key(text):
    """Field key if `text` is just a label ("Color......"), else None."""
    t = re.sub(r"[\s.·:_\-–]+$", "", text)
    for key, rx in _LABEL_RES.items():
        m = rx.match(t)
        if m and not m.group(1).strip():
            return key
    return None


def column_right_edge(lines, first):
    """Where the values of a label column end. Certificates put a diagram or a second panel
    beside the grading table; values never reach it. Taken from the first value box of the
    lines starting at the same left margin, ignoring far-right outliers (a label whose own
    value is missing gets chained to the next panel, e.g. "Color Grade | none")."""
    h = max(1.0, first[3] - first[1])
    ends = []
    for o in lines:
        if not o or abs(o[0][0] - first[0]) >= 2 * h or _label_at_start(o[0][4]) is None:
            continue
        if not _is_bare_label(o[0][4]):
            ends.append(o[0][2])   # label and value read as one box: "Color Grade ...... E"
        elif len(o) >= 2:
            ends.append(o[1][2])   # "Color Grade" | "E"
    ends.sort()
    if len(ends) < 3:
        return None
    med = ends[len(ends) // 2]
    return max(e for e in ends if e <= med + 4 * h)


def _label_at_start(text):
    for key, rx in _LABEL_RES.items():
        if rx.match(text):
            return key
    return None


def merge_words(lines):
    """Join boxes in a line that are only a word space apart into one phrase box. Windows OCR
    reports single words ("Color", "Grade"); PaddleOCR mostly reports phrases already."""
    out = []
    for ln in lines:
        merged = [ln[0]]
        for b in ln[1:]:
            p = merged[-1]
            h = min(p[3] - p[1], b[3] - b[1])
            if b[0] - p[2] < 0.8 * h:
                merged[-1] = (p[0], min(p[1], b[1]), b[2], max(p[3], b[3]), f"{p[4]} {b[4]}", min(p[5], b[5]))
            else:
                merged.append(b)
        out.append(merged)
    return out


def split_panels(lines):
    """Cut each line where it crosses into the next panel: boxes starting beyond the label
    column's right edge become a line of their own. Then put a label that was left alone back
    together with a value just right of it that sits a few pixels lower (it was chained elsewhere)."""
    out = []
    for ln in lines:
        edge = column_right_edge(lines, ln[0])
        h = ln[0][3] - ln[0][1]
        cut = next((i for i, b in enumerate(ln) if i > 0 and edge is not None and b[0] > edge + h), None)
        out.extend([ln[:cut], ln[cut:]] if cut else [ln])
    for ln in out:
        if len(ln) != 1 or not _is_bare_label(ln[0][4]):
            continue
        lab = ln[0]
        h = lab[3] - lab[1]
        edge = column_right_edge(out, lab)
        cands = [o for o in out if o and o is not ln and not _is_bare_label(o[0][4])
                 and lab[2] - 5 <= o[0][0] < lab[2] + 12 * h and (edge is None or o[0][0] < edge)
                 and _v_overlap(lab, o[0]) >= 0.3]
        if cands:
            best = max(cands, key=lambda o: _v_overlap(lab, o[0]))
            ln.extend(best)
            best.clear()
    # a label that ends its line with the value printed underneath ("Laserscribe on Girdle:"
    # / "IGI X1Y23456"): join the line directly below that starts under the label
    for ln in out:
        if not ln or len(ln) < 2 or not _is_bare_label(ln[-1][4]):
            continue
        lab = ln[-1]
        h = lab[3] - lab[1]
        below = [o for o in out if o and o is not ln and abs(o[0][0] - lab[0]) < 2 * h
                 and -0.3 * h <= o[0][1] - lab[3] <= 1.2 * h and _label_at_start(o[0][4]) is None]
        if below:
            nxt = min(below, key=lambda o: o[0][1])
            ln.extend(nxt)
            nxt.clear()
    out = [ln for ln in out if ln]
    out.sort(key=lambda ln: (min(b[1] for b in ln), ln[0][0]))
    return out


def _is_bare_label(text):
    return _bare_label_key(text) is not None


def _value_ok(key, value):
    value = ocr_fix(key, _clean_value(value or ""))
    valid = _VALID_RES.get(key)
    return bool(value) and (valid is None or bool(valid.match(value)))


def erase_leader_dots(region, text_h=None):
    """White out dot leaders ("......") so the recogniser sees only the value. A small blob
    with a character close on both sides (a decimal point) is kept. `text_h` is the height of
    the text line (the region may be taller). Returns the region trimmed to the remaining ink,
    or None if nothing but dots/background is left."""
    import cv2
    import numpy as np
    if region is None or region.size == 0:
        return None
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY) if region.ndim == 3 else region
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    n, _, stats, _ = cv2.connectedComponentsWithStats(bw)
    h = text_h or region.shape[0]
    comps = [stats[i] for i in range(1, n)]
    big = [c for c in comps if c[3] >= 0.35 * h]
    out = region.copy()
    for x, y, w, ch, area in comps:
        if ch >= 0.35 * h or w >= 0.35 * h:
            continue
        left = any(0 <= x - (b[0] + b[2]) <= 0.6 * h for b in big)
        right = any(0 <= b[0] - (x + w) <= 0.6 * h for b in big)
        if not (left and right):
            bw[y:y + ch, x:x + w] = 0
    out[bw == 0] = 255  # clean background: drops faint dots and paper texture
    ys, xs = np.nonzero(bw)
    if xs.size == 0:
        return None
    pad = int(0.4 * h)  # trim to the remaining ink so a lone "H" isn't lost in white space
    return out[:, max(0, xs.min() - pad):min(out.shape[1], xs.max() + pad + 1)]


def _level_strip(crop, lab, right, slope, h):
    """The strip right of a label, sheared so a slightly rotated photo line becomes level,
    then cut to that line's height (so the line above/below is not included)."""
    import cv2
    import numpy as np
    x0 = lab[2] + 2
    pad = abs(slope) * (right - x0) + h
    y0 = max(0, int(lab[1] - pad))
    big = crop(x0, y0, right, lab[3] + pad)
    if big is None or big.size == 0:
        return big
    if abs(slope) > 0.002:
        m = np.float32([[1, 0, 0], [-slope, 1, 0]])  # y' = y - slope * x
        big = cv2.warpAffine(big, m, (big.shape[1], big.shape[0]), flags=cv2.INTER_LINEAR,
                             borderValue=(255, 255, 255))
    top = max(0, int(lab[1] - y0 - h * 0.15))
    return big[top:int(lab[3] - y0 + h * 0.15)]


def _strip_label(text, label_text=""):
    """'Color Grade. H' -> 'H' using the field label patterns. If the label itself was misread
    ('Coore D'), drop as many leading words as the label has."""
    for rx in _LABEL_RES.values():
        m = rx.match(text)
        if m:
            return m.group(1)
    n = len(re.findall(r"[A-Za-z]+", re.sub(r"\(s\)", "", label_text)))
    words = [w for w in re.split(r"\s+|(?<!\d)[.:·]+|[.:·]+(?!\d)", text) if w]  # "Coor.D", not "2.01"
    return " ".join(words[n:]) if n and len(words) > n else ""


def _tidy(value):
    value = re.sub(r"[^\x20-\x7E°±×–]", "", value)  # drop stray non-Latin glyphs
    return re.sub(r"^[\s.·:_\-–,]+|[\s.·:_\-–,]+$", "", value)


def fill_missing_values(lines, img_w, recognize, crop):
    """For a line holding a bare label whose value is missing, fails the field's check
    (clarity read as ".S1") or was read with low confidence ("vS1" for VVS1 at 0.51),
    read the strip to its right once more and keep the more confident valid reading.
    The recogniser is shown "label + value" side by side (leader dots erased): a lone
    letter such as a colour grade is misread on its own but reliable with the label as context.
    `crop(x1, y1, x2, y2)` returns the image region; `recognize(region)` -> (text, score)."""
    import numpy as np
    slopes = sorted((ln[-1][1] - ln[0][1]) / (ln[-1][0] - ln[0][0])
                    for ln in lines if len(ln) >= 2 and ln[-1][0] - ln[0][0] > 50)
    slope = slopes[len(slopes) // 2] if slopes else 0.0
    for ln in lines:
        key = _bare_label_key(ln[0][4])
        if key is None:
            continue
        old = " ".join(b[4] for b in ln[1:])
        old_ok = bool(ln[1:]) and _value_ok(key, old)
        old_score = min((b[5] for b in ln[1:]), default=0.0)
        if old_ok and old_score >= REREAD_BELOW:
            continue
        lab = ln[0]
        h = lab[3] - lab[1]
        edge = column_right_edge(lines, lab)
        if edge is None:  # no clear column: furthest-reaching line from the same left margin
            col = [max(b[2] for b in other) for other in lines if abs(other[0][0] - lab[0]) < 2 * h]
            edge = max(col) if col else img_w
        right = min(img_w, edge + h)
        if right - lab[2] < h:
            continue
        y1, y2 = lab[1] - h * 0.15, lab[3] + h * 0.15
        label_img = crop(lab[0] - 2, y1, lab[2] + 2, y2)
        value_img = erase_leader_dots(_level_strip(crop, lab, right, slope, h), text_h=h)
        if value_img is None:  # nothing printed after the label
            continue
        hh = min(label_img.shape[0], value_img.shape[0])
        gap = np.full((hh, max(4, int(h * 0.5))) + label_img.shape[2:], 255, dtype=label_img.dtype)
        text, score = recognize(np.hstack([label_img[:hh], gap, value_img[:hh]]))
        value = _tidy(_strip_label(text or "", lab[4]))
        if not value:  # engine found the label but not the value beside it: read the value alone
            text, score = recognize(value_img)
            value = _tidy(text or "")
        if not value or score < 0.6:
            continue
        if not ln[1:] or (_value_ok(key, value) and (not old_ok or score > old_score)):
            ln[1:] = [(lab[2] + 2, lab[1], right, lab[3], value, score)]
    return lines


def lines_to_text(lines):
    out = []
    for ln in lines:
        parts, prev = [], None
        for b in ln:
            h = b[3] - b[1]
            if prev is not None:
                parts.append(" | " if b[0] - prev[2] > 1.2 * h else " ")
            parts.append(b[4].strip())
            prev = b
        out.append("".join(parts))
    return "\n".join(out)


def deskew(img, max_angle=6.0):
    """Straighten a slightly rotated photo/scan: pick the angle whose horizontal ink
    profile is sharpest (text lines line up), searched on a downscaled copy."""
    import cv2
    import numpy as np
    h, w = img.shape[:2]
    s = 800 / max(h, w)
    small = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA) if s < 1 else img
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    bw = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 25, 15)
    sh, sw = bw.shape
    center = (sw / 2, sh / 2)

    def score(angle):
        m = cv2.getRotationMatrix2D(center, angle, 1.0)
        prof = cv2.warpAffine(bw, m, (sw, sh)).sum(axis=1, dtype=np.float64)
        return float(np.sum(np.diff(prof) ** 2))

    angles = np.arange(-max_angle, max_angle + 0.01, 0.5)
    best = max(angles, key=score)
    fine = np.arange(best - 0.5, best + 0.51, 0.1)
    best = float(max(fine, key=score))
    if abs(best) < 0.3:
        return img
    m = cv2.getRotationMatrix2D((w / 2, h / 2), best, 1.0)
    return cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


# ── entry point ──────────────────────────────────────────────────────────────

def _decode(mime, data):
    import cv2
    import numpy as np
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Could not decode image")
    h, w = img.shape[:2]
    if max(h, w) > 4000:  # very large scans: keep CPU time reasonable
        s = 4000 / max(h, w)
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    return img


def _is_onednn_error(e):
    msg = str(e).lower()
    return any(k in msg for k in ("onednn", "mkldnn", "convertpirattribute2runtimeattribute"))


def run(pages):
    """pages: [(mime, bytes)] -> text (pages separated by blank lines)."""
    global _engine, _mkldnn
    with _lock:  # Paddle predictors are not thread-safe
        try:
            return _run(pages)
        except Exception as e:  # noqa: BLE001
            if not (_mkldnn and _is_onednn_error(e)):
                raise
            # this PaddlePaddle build cannot run these models with oneDNN: rebuild without it
            _mkldnn, _engine = False, None
            return _run(pages)


def _run(pages):
    return process_pages(pages, _detect, _recognize)


def process_pages(pages, detect, recognize):
    """Engine-independent page pipeline: decode, deskew, detect boxes, build lines,
    re-read doubtful values. `detect(img)` -> [(x1, y1, x2, y2, text, score)];
    `recognize(img)` -> (text, score). Used by the PaddleOCR and Windows OCR engines."""
    texts = []
    for mime, data in pages:
        img = deskew(_decode(mime, data))
        lines = split_panels(merge_words(group_lines(detect(img))))
        H, W = img.shape[:2]

        def crop(x1, y1, x2, y2):
            return img[max(0, int(y1)):min(H, int(y2)), max(0, int(x1)):min(W, int(x2))]

        fill_missing_values(lines, W, recognize, crop)
        texts.append(lines_to_text(lines))
    return "\n\n".join(texts)

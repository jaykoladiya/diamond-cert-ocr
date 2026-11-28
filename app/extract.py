"""Pull diamond-grading fields out of OCR'd certificate text (GIA, IGI, HRD, AGS, GCAL, ...).

Strategy: flatten the Markdown/HTML from the OCR into an ordered list of text tokens
(one per line / table cell), find "Label ...... Value" pairs with per-field label
patterns, and accept a value only if it passes the field's validator. Fields still
missing afterwards are filled from value-only patterns scanned over the whole text.
"""
import difflib
import html
import re
from collections import OrderedDict

# (key, column header) — order is the Excel column order.
FIELDS = [
    ("lab", "Lab"),
    ("report_number", "Report Number"),
    ("report_date", "Report Date"),
    ("origin", "Natural / Lab-Grown"),
    ("growth_method", "Growth Method"),
    ("shape", "Shape & Cutting Style"),
    ("measurements", "Measurements"),
    ("length_mm", "Length (mm)"),
    ("width_mm", "Width (mm)"),
    ("depth_mm", "Depth (mm)"),
    ("carat", "Carat Weight"),
    ("color", "Color"),
    ("fancy_color", "Fancy Color"),
    ("fancy_intensity", "Fancy Intensity"),
    ("fancy_overtone", "Fancy Overtone"),
    ("clarity", "Clarity"),
    ("cut", "Cut"),
    ("polish", "Polish"),
    ("symmetry", "Symmetry"),
    ("fluorescence", "Fluorescence"),
    ("fluor_color", "Flr Color"),
    ("depth_pct", "Depth %"),
    ("table_pct", "Table %"),
    ("crown_height", "Crown Height %"),
    ("crown_angle", "Crown Angle"),
    ("pavilion_depth", "Pavilion Depth %"),
    ("pavilion_angle", "Pavilion Angle"),
    ("girdle", "Girdle"),
    ("culet", "Culet"),
    ("inscription", "Inscription"),
    ("comments", "Comments"),
]
FIELD_KEYS = [k for k, _ in FIELDS]
HEADERS = dict(FIELDS)
KEY_FIELDS = ["report_number", "shape", "carat", "color", "clarity"]

GRADE = r"(?:excellent|very\s*good|good|fair|poor|ideal|ex|vg|gd)"
CLARITY = r"(?:FL|IF|LC|VVS\s*[12]|VS\s*[12]|SI\s*[123]|I\s*[123]|P\s*[123])"
FLUOR = r"(?:none|nil|negligible|inert|faint|very\s*slight|slight|medium|moderate|very\s*strong|strong)"

# key -> (label regex, value validator regex or None)
LABELS = OrderedDict([
    ("report_number", (r"(?:(?:gia|igi|hrd|ags|gcal)\s*)?(?:grading\s*)?(?:(?:report|certificate|cert\.?|dossier)\s*)?(?:number|no\.?|num\.?|#)",
                       r"(?=(?:\D*\d){5})[A-Z]{0,3}\s*[A-Z0-9][A-Z0-9\s-]{5,}")),
    ("report_date", (r"(?:report\s*)?date(?:\s*of\s*issue)?|issue\s*date|issued\s*on", r".*\d.*")),
    ("description", (r"description|diamond\s*type|nature|origin", None)),
    ("shape", (r"shape\s*(?:and|&)\s*cut(?:ting)?\s*style|shape\s*(?:and|&|/)\s*cut|shape|cutting\s*style",
               r"(?=.*(?:round|oval|princess|cushion|emerald|pear|marquise|heart|radiant|asscher|square|rectangular"
               r"|triang|trilliant|baguette|european|mine|rose|brilliant|modified|step|cut))[A-Za-z].*")),
    ("measurements", (r"measurements?|dimensions?", r".*\d.*")),
    ("carat", (r"carat\s*weight|weight|carats?", r"\d{1,3}\s*[.,]\s*\d{1,3}.*")),
    ("color", (r"colou?r\s*grade|colou?r(?!\s*(?:scale|origin|distribution))",
               r"(?:[D-Z](?:\s*(?:-|to)\s*[D-Z])?|(?:natural\s*)?fancy\b.*|faint\b.*|very\s*light\b.*|light\b.*)\s*(?:\(.*\))?")),
    ("clarity", (r"clarity\s*grade|clarity(?!\s*characteristics)", CLARITY + r"\b.*")),
    ("cut", (r"cut\s*grade|cut(?!ting)", GRADE + r"\b.*")),
    ("polish_symmetry", (r"polish\s*(?:and|&|/)\s*symmetry", GRADE + r"\b.*")),
    ("polish", (r"polish", GRADE + r"\b.*")),
    ("proportions", (r"proportions?(?:\s*grade)?", GRADE + r"\b.*")),
    ("symmetry", (r"symmetry", GRADE + r"\b.*")),
    ("fluorescence", (r"(?:fl[ou]{1,2}r?e?s?c?[ae]n[cs]e|fluor\.?|fluo\.?|flr)(?:\s*intensity)?", FLUOR + r"\b.*")),
    ("depth_pct", (r"total\s*depth(?:\s*%)?|depth\s*(?:%|percentage)?", r"\d{2}(?:[.,]\d+)?\s*%?")),
    ("table_pct", (r"table\s*(?:size|width|diameter|%)?", r"\d{2}(?:[.,]\d+)?\s*%?")),
    # IGI: "Crown Height - Angle   17.5% - 37.8°" (both values on one line)
    ("crown_pair", (r"crown\s*he[il1]ght\s*[-–/&]\s*angle", r"\d.*\d.*")),
    ("pavilion_pair", (r"pavilion\s*depth\s*[-–/&]\s*angle", r"\d.*\d.*")),
    ("crown_height", (r"crown\s*he[il1]ght(?:\s*%)?", r"\d{1,2}(?:[.,]\d+)?\s*%?")),
    ("pavilion_depth", (r"pavilion\s*depth(?:\s*%)?", r"\d{1,2}(?:[.,]\d+)?\s*%?")),
    ("crown_angle", (r"crown\s*angle", r"\d{2}(?:[.,]\d+)?\s*°?.*")),
    ("pavilion_angle", (r"pavilion\s*angle", r"\d{2}(?:[.,]\d+)?\s*°?.*")),
    ("girdle", (r"girdle(?:\s*thickness)?", r"[A-Za-z].*")),
    ("culet", (r"culet(?:\s*size)?", r"[A-Za-z].*")),
    ("inscription", (r"(?:laser\s*)?inscriptions?(?:\s*\(s\))?|inscription\(s\)|laser\s*scr[il]?be(?:\s*on\s*girdle)?", r".+")),
    ("comments", (r"comments?|remarks?|additional\s*comments?", r".+")),
])
_LABEL_RES = {k: re.compile(r"^\s*(?:" + lab + r")\s*(?:\(s\))?\s*[:：|\-–]?\s*(.*)$", re.I)
              for k, (lab, _) in LABELS.items()}
_VALID_RES = {k: re.compile(r"^(?:" + v + r")$", re.I) if v else None for k, (_, v) in LABELS.items()}

LABS = [
    ("GIA", r"\bG[I1l]A\b|gemological\s+institute\s+of\s+america"),
    ("IGI", r"\bIGI\b|international\s+gemological\s+institute"),
    ("HRD", r"\bHRD\b|hoge\s+raad\s+voor\s+diamant"),
    ("AGS", r"\bAGSL?\b|american\s+gem\s+society"),
    ("GCAL", r"\bGCAL\b|gem\s+certification\s*(?:&|and)\s*assurance"),
    ("GSI", r"\bGSI\b|gemological\s+science\s+international"),
    ("EGL", r"\bEGL\b|european\s+gemological"),
    ("IIDGR", r"\bIIDGR\b"),
]
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
MEAS_RE = re.compile(
    r"(\d{1,2}[.,]\d{1,3})\s*(?:[-–~]\s*(\d{1,2}[.,]\d{1,3})\s*)?[x×X*]\s*(\d{1,2}[.,]\d{1,3})"
    r"(?:\s*[x×X*]\s*(\d{1,2}[.,]\d{1,3}))?\s*(?:mm)?")


# ── text preparation ─────────────────────────────────────────────────────────

def to_tokens(text):
    """Flatten OCR Markdown/HTML into an ordered list of short text tokens."""
    t = text or ""
    t = re.sub(r"<\s*/t[dh]\s*>\s*<\s*t[dh][^>]*>", "\n", t, flags=re.I)   # cell boundary
    t = re.sub(r"<\s*/?\s*(tr|table|br|p|div|li|thead|tbody)[^>]*>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)            # image refs
    t = re.sub(r"(?m)^\s*#{1,6}\s*", "", t)                 # headings
    t = re.sub(r"\*\*|__|`", "", t)
    t = re.sub(r"\s*(?:\.\s*){3,}|\s*…+\s*|_{3,}", " : ", t)  # dotted leaders
    tokens = []
    for line in t.split("\n"):
        for cell in re.split(r"\s*\|\s*", line):            # markdown table cells
            cell = re.sub(r"[ \t]+", " ", cell).strip(" :\t")
            if cell and not re.fullmatch(r"[-:\s]+", cell):
                tokens.append(cell)
    return tokens


def _is_label(token):
    if re.fullmatch(r"\s*no\.?\s*", token, re.I):  # a bare "No" is a value (fluorescence "No"), not a label
        return False
    return any(r.match(token) and not r.match(token).group(1).strip() for r in _LABEL_RES.values())


def _clean_value(v):
    v = re.sub(r"\s+", " ", v).strip(" :|-–\t·,")
    v = re.sub(r"^[.\s]+", "", v)                     # leftover leader dots
    return re.sub(r"(?:\s*\.{2,}|\s+\.)$", "", v).strip()  # keep a sentence's full stop


def _fuzzy(value, vocab, cutoff=0.75):
    """Closest vocabulary word for an OCR-garbled value ("Excelent" -> "excellent").
    Returns None if nothing is close or two words are equally close ("pood": good/poor)."""
    v = value.lower().strip()
    scored = sorted(((difflib.SequenceMatcher(None, v[:len(w) + 2], w).ratio(), w) for w in vocab),
                    reverse=True)
    if scored and scored[0][0] >= cutoff and (len(scored) == 1 or scored[0][0] > scored[1][0]):
        return scored[0][1]
    return None


FANCY_WORDS = ["fancy", "light", "intense", "vivid", "deep", "dark", "brown", "brownish", "yellow", "yellowish",
               "pink", "pinkish", "purple", "purplish", "blue", "bluish", "green", "greenish", "orange", "orangy",
               "gray", "grayish", "grey", "greyish", "black", "white", "red", "reddish", "violet", "olive", "chameleon"]
SHAPE_WORDS = ["round", "brilliant", "modified", "oval", "princess", "cushion", "emerald", "pear", "marquise",
               "heart", "radiant", "asscher", "square", "rectangular", "step", "triangular", "baguette",
               "octagonal", "european", "mine", "rose", "trilliant", "shield", "kite", "half", "moon"]
# Rapaport Trade's accepted fluorescence values (help.rapaport.com "Diamond Fields & Values")
RAP_FLUOR = {"N": "None", "NON": "None", "NO": "None", "NIL": "None", "FL0": "None", "NONE": "None",
             "F": "Faint", "FNT": "Faint", "FA": "Faint", "FL1": "Faint",
             "M": "Medium", "MED": "Medium", "FL2": "Medium",
             "S": "Strong", "STG": "Strong", "ST": "Strong", "FL3": "Strong",
             "VS": "Very Strong", "VST": "Very Strong", "VSTG": "Very Strong", "FL4": "Very Strong",
             "SL": "Slight", "SLI": "Slight", "SLT": "Slight",
             "VSL": "Very Slight", "VSLG": "Very Slight", "VSLT": "Very Slight"}
GRADE_WORDS = ["excellent", "very good", "good", "fair", "poor", "ideal"]
FLUOR_WORDS = ["none", "faint", "medium", "strong", "very strong", "negligible", "slight"]


def ocr_fix(key, v):
    """Repair common OCR character confusions before a value is validated."""
    if key == "clarity":
        words = re.sub(r"[^a-z ]", "", v.lower()).strip()
        if difflib.SequenceMatcher(None, words[:19], "internally flawless").ratio() >= 0.8:
            return "IF"                                         # also "Internaly Flawles"
        if difflib.SequenceMatcher(None, words[:8], "flawless").ratio() >= 0.8:
            return "FL"
        if difflib.SequenceMatcher(None, words[:11], "loupe clean").ratio() >= 0.8:
            return "LC"                                         # older HRD/IGI term, kept as printed
        t = re.sub(r"\s+", "", v.upper()).replace("W", "VV")      # WS1 -> VVS1
        t = re.sub(r"^V{3,}", "VV", t)                            # WVS2 / VWVS2 -> VVS2
        t = re.sub(r"^(VV|V)5", r"\1S", t)                      # VV51 -> VVS1
        t = re.sub(r"^5([I1L|!])", r"S\1", t)                     # 5I1 -> SI1
        t = re.sub(r"^S[1IL|!]([123])$", r"SI\1", t)          # S12 / SL2 -> SI2
        t = re.sub(r"^(VV?S)[IL|!]$", r"\g<1>1", t)            # VVSI -> VVS1
        t = re.sub(r"^SI[IL|!]$", "SI1", t)
        t = re.sub(r"^[1L|!]F$", "IF", t)                      # 1F -> IF
        t = re.sub(r"^F[1I|!]$", "FL", t)
        return t
    if key == "inscription":
        return re.sub(r"\bG[lI1|!]A\b", "GIA", v)
    if key == "shape":  # "Marqulse" -> "marquise", so the shape check recognises it
        return " ".join((difflib.get_close_matches(w.lower(), SHAPE_WORDS, 1, 0.8) or [w])[0]
                        if w.isalpha() and len(w) > 3 else w for w in v.split())
    if key == "color":
        t = v.strip()
        return t.upper() if re.fullmatch(r"[d-z]", t) else t
    if key in ("cut", "polish", "symmetry") and not re.match(GRADE + r"\b", v, re.I):
        return _fuzzy(v, GRADE_WORDS) or v
    if key == "fluorescence":
        code = re.sub(r"[\s.]", "", v).upper()
        if code in RAP_FLUOR:  # Rapaport codes: N, FNT, MED, STG, VST, SL, VSL, FL0-FL4, ...
            return RAP_FLUOR[code]
        v = re.sub(r"(?i)([a-z])(blue|yellow|green|white|orange|red)\b", r"\1 \2", v)  # "MediumBlue"
        if not re.match(FLUOR + r"\b", v, re.I):
            fixed = _fuzzy(v.split()[0] if v.split() else v, FLUOR_WORDS)
            return f"{fixed} {' '.join(v.split()[1:])}".strip() if fixed else v
    return v


# ── normalisers ──────────────────────────────────────────────────────────────

def _num(s):
    m = re.search(r"\d+(?:[.,]\d+)?", s or "")
    return float(m.group().replace(",", ".")) if m else None


def _title(s):
    return " ".join(w if any(ch.isdigit() for ch in w) else w.capitalize() for w in s.split())


def _grade(s):
    s = s.strip()
    names = {"ex": "Excellent", "vg": "Very Good", "gd": "Good", "verygood": "Very Good", "excellent": "Excellent",
             "good": "Good", "fair": "Fair", "poor": "Poor", "ideal": "Ideal"}
    m = re.match(GRADE, s, re.I)
    if not m:
        return s
    return names[re.sub(r"\s+", "", m.group(0).lower())]


def normalise_date(s):
    s = re.sub(r"\b0(?=[a-z]{2,8}\b)|\b0(?=ct)", "O", s.strip(), flags=re.I)  # "0ctober" -> "October"
    month = r"((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*)"
    m = re.search(month + r"\.?\s*(\d{1,2})[,.]?\s*(\d{4})", s, re.I)        # January 15, 2024
    if m and m.group(1)[:3].lower() in MONTHS:
        return f"{m.group(3)}-{MONTHS[m.group(1)[:3].lower()]:02d}-{int(m.group(2)):02d}"
    m = re.search(r"(\d{1,2})\s*" + month + r"\.?[,.]?\s*(\d{4})", s, re.I)        # 15 January 2024
    if m and m.group(2)[:3].lower() in MONTHS:
        return f"{m.group(3)}-{MONTHS[m.group(2)[:3].lower()]:02d}-{int(m.group(1)):02d}"
    m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)               # 2024-01-15
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", s)               # 15/01/2024 (day first)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        day, mon = (b, a) if b > 12 else (a, b)
        return f"{m.group(3)}-{mon:02d}-{day:02d}"
    return s


def normalise(key, v):
    if v is None or v == "":
        return v
    if key == "report_number":
        return re.sub(r"[\s-]", "", v).upper()
    if key == "report_date":
        return normalise_date(v)
    if key == "carat":
        return _num(v)
    if key == "inscription":
        return re.sub(r"\bG[lI1|!]A\b", "GIA", v)
    if key == "color":
        m = re.match(r"([D-Z])(?:\s*(?:-|to)\s*([D-Z]))?\b", v.strip(), re.I)
        if m and len(v.strip()) <= 12:
            return m.group(1).upper() + (f"-{m.group(2).upper()}" if m.group(2) else "")
        v = re.sub(r"(?i)^natural\s*(?=fancy)", "", v.strip())
        words = [(difflib.get_close_matches(w.lower(), FANCY_WORDS, 1, 0.8) or [w])[0] if w.isalpha() and len(w) > 3 else w
                 for w in v.split()]                                              # Browr -> brown
        return _title(" ".join(words))
    if key == "clarity":
        m = re.match(CLARITY, v.strip(), re.I)
        return re.sub(r"\s+", "", m.group(0)).upper() if m else v
    if key in ("cut", "polish", "symmetry"):
        return _grade(v)
    if key == "fluorescence":
        m = re.match(FLUOR + r"(?:\s*\(?\s*(blue|yellow|green|white|orange|red)\)?)?", v.strip(), re.I)
        if not m:
            return v
        word = re.sub(r"\s+", " ", m.group(0)[:len(m.group(0)) - len(m.group(1) or "")].strip(" ("))
        return _title(f"{word} {m.group(1)}" if m.group(1) else word)   # "MediumBlue" -> "Medium Blue"
    if key in ("depth_pct", "table_pct"):
        n = _num(v)
        return n
    if key in ("crown_angle", "pavilion_angle", "crown_height", "pavilion_depth"):
        return _num(v)
    if key == "shape":
        v = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", v)  # RoundBrilliant
        v = re.sub(r"(?i)(?<=[a-z])(?=(?:brilliant|modified|step|cut)\b)", " ", v)  # Roundbrilliant
        words = [(difflib.get_close_matches(w.lower(), SHAPE_WORDS, 1, 0.8) or [w])[0] if w.isalpha() and len(w) > 3 else w
                 for w in v.split()]                                              # Briliant -> brilliant
        return _title(" ".join(words))
    return v


# ── extraction ───────────────────────────────────────────────────────────────

def _is_scale(key, value, following):
    """True when a colour/clarity label is followed by the grading scale, not a grade."""
    for n, t in enumerate(following):  # what belongs to this label ends at the next label
        if _is_label(t):
            following = following[:n]
            break
    if key == "clarity":
        hits = [t for t in [value, *following] if re.fullmatch(r"(VVS|VS|SI|I|P)\s?[123]|FL|IF", t.strip(), re.I)]
        return len(hits) >= 2 or len(re.findall(r"\b(?:VVS|VS|SI)\s?[12]\b", value, re.I)) >= 2
    letters = [t for t in [value, *following] if re.fullmatch(r"[D-Z]", t.strip())]
    return len(letters) >= 3 or bool(re.fullmatch(r"(?:[D-Z]\s+){3,}[D-Z].*", value.strip()))


def extract_fields(text):
    """Return an OrderedDict of FIELD_KEYS -> value (None when not found)."""
    tokens = to_tokens(text)
    flat = "\n".join(tokens)
    found = {}

    for i, tok in enumerate(tokens):
        for key, rx in _LABEL_RES.items():
            if key in found:
                continue
            m = rx.match(tok)
            if not m:
                continue
            value = _clean_value(m.group(1))
            nxt = i + 1                      # first token after the value
            if not value and i + 1 < len(tokens) and not _is_label(tokens[i + 1]):
                value = _clean_value(tokens[i + 1])
                nxt = i + 2
            if not value:
                continue
            if key in ("clarity", "color") and _is_scale(key, value, tokens[nxt:nxt + 5]):
                continue  # "CLARITY GRADE: Internally Flawless VVS1 VVS2 ...": the printed scale
            value = ocr_fix(key, value)
            valid = _VALID_RES[key]
            if valid and not valid.match(value):
                continue
            found[key] = value
            break  # one field per token

    if "polish_symmetry" in found:  # IGI: one grade for both
        found.setdefault("polish", found["polish_symmetry"])
        found.setdefault("symmetry", found["polish_symmetry"])
    if "proportions" in found:      # IGI: proportions grade stands in for cut grade
        found.setdefault("cut", found["proportions"])
    for pair, (pct, angle) in (("crown_pair", ("crown_height", "crown_angle")),
                               ("pavilion_pair", ("pavilion_depth", "pavilion_angle"))):
        nums = re.findall(r"\d{1,2}(?:[.,]\d+)?", found.get(pair, ""))
        if len(nums) >= 2:
            found.setdefault(pct, nums[0])
            found.setdefault(angle, nums[1])
    out = OrderedDict((k, None) for k in FIELD_KEYS)
    for k in FIELD_KEYS:
        if k in found:
            out[k] = normalise(k, found[k])

    # Lab
    for name, rx in LABS:
        if re.search(rx, flat, re.I):
            out["lab"] = name
            break

    # Value-only fallbacks
    if not out["measurements"] or not MEAS_RE.search(str(out["measurements"])):
        m = MEAS_RE.search(flat)
        if m:
            out["measurements"] = m.group(0).strip()
    m = MEAS_RE.search(str(out["measurements"] or ""))
    if m:
        out["measurements"] = m.group(0).strip()
        parts = [float(g.replace(",", ".")) for g in m.groups() if g]
        if len(parts) == 3 and m.group(2):          # "6.45 - 6.48 x 3.98" (round: min-max x depth)
            out["length_mm"], out["width_mm"], out["depth_mm"] = parts
        elif len(parts) == 3:                      # "L x W x D"
            out["length_mm"], out["width_mm"], out["depth_mm"] = parts
        elif len(parts) == 4:
            out["length_mm"], out["width_mm"], out["depth_mm"] = parts[1], parts[2], parts[3]
        if not out["measurements"].lower().endswith("mm"):
            out["measurements"] = out["measurements"] + " mm"

    if out["carat"] is None:
        m = re.search(r"(\d{1,2}[.,]\d{2,3})\s*(?:carats?|cts?)\b", flat, re.I)
        if m:
            out["carat"] = _num(m.group(1))
    if out["clarity"] is None:  # no labelled grade: only if exactly one grade appears (not a printed scale)
        grades = {re.sub(r"\s", "", g).upper()
                  for g in re.findall(r"\b(FL|IF|VVS\s?[12]|VS\s?[12]|SI\s?[123]|I[123])\b", flat)}
        if len(grades) == 1:
            out["clarity"] = grades.pop()
    if out["report_number"] is None:
        m = re.search(r"(?:report|certificate|no\.?|#)\D{0,15}((?:LG)?\d{7,10})\b", flat, re.I)
        if m:
            out["report_number"] = m.group(1).upper()
    if out["report_date"] is None:  # GIA prints the date unlabelled at the top
        for tok in tokens[:40]:
            d = normalise_date(tok)
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) and len(tok) <= 30:
                out["report_date"] = d
                break
    if out["inscription"] is None:
        m = re.search(r"\b((?:GIA|IGI|LG)\s?\d{7,10})\b", flat)
        if m and out["report_number"] and re.sub(r"\D", "", m.group(1)) == re.sub(r"\D", "", out["report_number"]):
            out["inscription"] = m.group(1)

    # Natural vs lab-grown and growth method
    desc = (found.get("description") or "") + "\n" + flat
    if re.search(r"lab(?:oratory)?[\s-]*(?:grown|created)|\bCVD\b|\bHPHT\b|chemical\s+vapou?r\s+deposition|high\s+pressure\s+high\s+temperature", desc, re.I) \
            or re.match(r"LG\d", str(out["report_number"] or "")):
        out["origin"] = "Lab-Grown"
    elif re.search(r"natural\s*diamond|diamond", desc, re.I):
        out["origin"] = "Natural"
    if re.search(r"\bCVD\b|chemical\s+vapou?r\s+deposition", flat, re.I):
        out["growth_method"] = "CVD"
    elif re.search(r"\bHPHT\b|high\s+pressure\s+high\s+temperature", flat, re.I):
        out["growth_method"] = "HPHT"
    return out


def missing_key_fields(record):
    return [k for k in KEY_FIELDS if record.get(k) in (None, "")]

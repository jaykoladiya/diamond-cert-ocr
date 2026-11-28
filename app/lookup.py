"""Fill rows from GIA report numbers: download the report PDF and read its text layer.

The PDF address is a template (REPORT_PDF_URL, "{report}" is replaced by the number). The
default is the report-PDF link a supplier includes in its public stock lists; set the variable
to another source, or to "off" to disable lookups. Requests go one at a time with a pause in
between, and every PDF is kept on disk so a report is downloaded only once.
"""
import os
import re
import threading
import time
from pathlib import Path

import requests

REPORT_PDF_URL = os.environ.get(
    "REPORT_PDF_URL", "")
CACHE_DIR = Path(os.environ.get("REPORT_CACHE_DIR", Path(__file__).resolve().parent.parent / "reports"))
PAUSE_SECONDS = float(os.environ.get("REPORT_PAUSE_SECONDS", "1.0"))
TIMEOUT = int(os.environ.get("REPORT_TIMEOUT", "60"))
MAX_PER_REQUEST = 50
USER_AGENT = "DiamondCertPortal/1.0 (report lookup)"

_lock = threading.Lock()  # one download at a time, across all users of the portal
_last = [0.0]


class ReportLookupError(RuntimeError):
    pass


def enabled():
    return REPORT_PDF_URL.strip().lower() not in ("", "off", "0", "false", "no")


def parse_numbers(text):
    """GIA report numbers from pasted text: one per line, or whole stock-list lines/links.
    GIA numbers are 10 digits (older reports 7-9). Duplicates are dropped, order kept."""
    seen, out = set(), []
    for m in re.finditer(r"(?<![\d.])(\d{7,10})(?![\d.])", text or ""):
        n = m.group(1)
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def cached_pdf(report):
    p = CACHE_DIR / f"GIA_{report}.pdf"
    return p if p.exists() else None


def fetch_pdf(report):
    """PDF bytes for a GIA report number (from the cache if downloaded before)."""
    if not re.fullmatch(r"\d{7,10}", report):
        raise ReportLookupError(f"{report}: not a GIA report number")
    hit = cached_pdf(report)
    if hit:
        return hit.read_bytes()
    if not enabled():
        raise ReportLookupError("Report lookup is turned off (REPORT_PDF_URL)")
    url = REPORT_PDF_URL.replace("{report}", report)
    with _lock:
        wait = _last[0] + PAUSE_SECONDS - time.time()
        if wait > 0:
            time.sleep(wait)
        try:
            r = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
        except requests.RequestException as e:
            raise ReportLookupError(f"{report}: could not reach the report service ({e.__class__.__name__})") from e
        finally:
            _last[0] = time.time()
    if r.status_code != 200 or not r.content.startswith(b"%PDF"):
        raise ReportLookupError(f"{report}: no report PDF returned (HTTP {r.status_code})")
    return r.content


def lookup(report):
    """(pdf_bytes, text) for a report number; raises ReportLookupError if it can't be read."""
    from .ocr import pdf_text
    data = fetch_pdf(report)
    text = pdf_text(data)
    if not text:
        raise ReportLookupError(f"{report}: the PDF has no readable report data")
    if report not in re.sub(r"\s", "", text):
        raise ReportLookupError(f"{report}: the PDF returned is for a different report")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"GIA_{report}.pdf"
    if not path.exists():
        path.write_bytes(data)
    return data, text

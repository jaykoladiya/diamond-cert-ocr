"""Fill rows from GIA report numbers: download the report PDF and read its text layer.

The PDF address is a link template ("{report}" is replaced by the number). It is not part
of the code: paste one example link in the portal's settings (saved on this computer in
local_settings.json, which is kept out of git), or set REPORT_PDF_URL. Until one is set,
lookups are off. Requests go one at a time with a pause in between, and every PDF is kept
on disk so a report is downloaded only once.
"""
import json
import os
import re
import threading
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
SETTINGS_FILE = Path(os.environ.get("PORTAL_SETTINGS_FILE", ROOT / "local_settings.json"))
CACHE_DIR = Path(os.environ.get("REPORT_CACHE_DIR", ROOT / "reports"))
PAUSE_SECONDS = float(os.environ.get("REPORT_PAUSE_SECONDS", "1.0"))
TIMEOUT = int(os.environ.get("REPORT_TIMEOUT", "60"))
MAX_PER_REQUEST = 50
USER_AGENT = "DiamondCertPortal/1.0 (report lookup)"

_lock = threading.Lock()  # one download at a time, across all users of the portal
_last = [0.0]


class ReportLookupError(RuntimeError):
    pass


def _read_settings():
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def link_template():
    """The report-PDF link template in use: REPORT_PDF_URL if set, else the saved setting."""
    env = os.environ.get("REPORT_PDF_URL", "").strip()
    if env:
        return "" if env.lower() in ("off", "0", "false", "no") else env
    return str(_read_settings().get("report_pdf_url") or "").strip()


def to_template(link):
    """Turn a pasted example link into a template: its GIA number becomes {report}."""
    link = (link or "").strip()
    if not link:
        return ""
    if not re.match(r"https?://[^\s/]+\.[^\s/]+", link, re.I):
        raise ValueError("Paste a full link starting with http:// or https://")
    if "{report}" in link:
        return link
    nums = list(re.finditer(r"(?<![\d.])\d{7,10}(?![\d.])", link))
    if not nums:
        raise ValueError("The link should contain a GIA report number (for example one you looked up before)")
    m = nums[-1]
    return link[:m.start()] + "{report}" + link[m.end():]


def save_link(link):
    """Save the report link (or clear it with ""); returns the template now in use."""
    template = to_template(link)
    data = _read_settings()
    if template:
        data["report_pdf_url"] = template
    else:
        data.pop("report_pdf_url", None)
    SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return template


def enabled():
    return bool(link_template())


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
    template = link_template()
    if not template:
        raise ReportLookupError("No report link set: paste one in ⚙ Settings")
    url = template.replace("{report}", report)
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

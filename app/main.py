"""Diamond certificate portal: upload certificates -> Unlimited-OCR-2 -> fields -> Excel."""
import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from . import ocr
from .excel import COLUMNS, build_workbook, format_record
from .extract import KEY_FIELDS, extract_fields, missing_key_fields

STATIC = Path(__file__).parent / "static"
MAX_FILE_MB = int(os.environ.get("MAX_FILE_MB", "25"))
CONCURRENCY = int(os.environ.get("OCR_CONCURRENCY", "4"))

app = FastAPI(title="Diamond Certificate Portal")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
_sem = asyncio.Semaphore(CONCURRENCY)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/status")
def status():
    return ocr.server_status()


@app.get("/api/columns")
def columns():
    return {"columns": [{"key": k, "header": h} for k, h in COLUMNS], "key_fields": KEY_FIELDS}


async def _process(upload: UploadFile, engine: str | None = None):
    name = upload.filename or "upload"
    data = await upload.read()
    if len(data) > MAX_FILE_MB * 1024 * 1024:
        return {"source_file": name, "error": f"File larger than {MAX_FILE_MB} MB"}
    async with _sem:
        try:
            raw, markdown = await run_in_threadpool(ocr.run_ocr, name, data, engine)
        except ocr.OCRError as e:
            return {"source_file": name, "error": str(e)}
        except Exception as e:  # noqa: BLE001 - surface anything else per file
            return {"source_file": name, "error": f"{type(e).__name__}: {e}"}
    record = dict(extract_fields(markdown))
    record["source_file"] = name
    record = format_record(record)  # same codes and layout as the Excel export
    return {"source_file": name, "record": record, "missing": missing_key_fields(record),
            "markdown": markdown}


@app.post("/api/extract")
async def extract(files: list[UploadFile] = File(...), engine: str = Form("auto")):
    if not files:
        raise HTTPException(400, "No files uploaded")
    if engine not in ("auto", *ocr.ENGINE_LABELS):
        raise HTTPException(400, f"Unknown engine: {engine}")
    return {"results": await asyncio.gather(*(_process(f, engine) for f in files))}


@app.post("/api/export")
async def export(records: str = Form(...), template: UploadFile | None = File(None)):
    try:
        rows = json.loads(records)
        assert isinstance(rows, list)
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "records must be a JSON list")
    tpl = await template.read() if template is not None else None
    if tpl and not (template.filename or "").lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(400, "Template must be an .xlsx file")
    try:
        data, info = build_workbook(rows, tpl or None)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Could not write workbook: {e}")
    fname = (template.filename if tpl else
             f"diamond_certificates_{datetime.now():%Y%m%d_%H%M}.xlsx")
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"',
                             "X-Export-Info": json.dumps(info)})

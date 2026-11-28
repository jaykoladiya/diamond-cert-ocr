# Diamond Certificate Portal

Upload diamond grading certificates (GIA, IGI, HRD, AGS, GCAL, ...) as PDFs, scans or phone photos.
The portal reads them with OCR, pulls out the grading fields, shows them in an editable table, and
exports to Excel: either a new workbook, or rows appended to **your own** `.xlsx` (matched by column header).

Three OCR engines. Pick one in the **Engine** menu at the top of the page, or leave it on
**Automatic**, which uses the first available in this order:

| Engine | Runs on | Notes |
|---|---|---|
| [Unlimited-OCR-2](https://github.com/baidu/Unlimited-OCR) | NVIDIA GPU with ~16-24 GB+ VRAM, via SGLang | used when its server at `OCR_URL` answers |
| **Windows OCR** | Windows 10/11, built in | the engine behind PowerToys Text Extractor (`Windows.Media.Ocr`); instant, no download |
| **PaddleOCR** | any PC, CPU only | downloads ~100 MB of models on first use; reports confidence, so doubtful values get re-read |

`OCR_BACKEND=unlimited|windows|paddle` sets the default instead of Automatic.

## Quick start on Windows (no GPU needed)
1. Install 64-bit Python 3.10-3.13 from python.org (tick "Add python.exe to PATH").
   (3.9 works with PaddleOCR only; Windows OCR needs 3.10+.)
2. Double-click `start.bat`. It installs packages into `.venv` on the first run and again whenever
   `requirements.txt` changes. The browser opens at http://localhost:8000.
3. The header should show "Using Windows OCR (built in)". If Windows OCR shows as unavailable, add the
   English OCR component: Settings > Time & language > Language & region > English > Language options >
   Optical character recognition, or in an admin PowerShell:
   `Add-WindowsCapability -Online -Name "Language.OCR~~~en-US~0.0.1.0"`.

Linux / macOS: `pip install -r requirements.txt && ./run.sh`.

### Paste bar
The bar at the top takes whatever you paste:
- **A certificate image**: take a screenshot (Win+Shift+S) or copy an image (WhatsApp, a website, a file in
  Explorer) and press **Ctrl+V** anywhere on the page. It is read straight away. **📋 Paste** does the same with
  a click (the browser asks once for clipboard permission).
- **GIA report numbers**: paste or type them (or whole stock-list lines) and press **Enter** / **Look up**.

**📁 Upload files** and drag-and-drop still work as before.

### Look up GIA reports by number
Paste GIA report numbers into the paste bar (one per line, or whole stock-list lines: the 7-10 digit numbers
are picked out) and press **Enter** or **Look up**. Each report PDF is downloaded and read from its
text layer, so the row is exact; the 👁 viewer shows the PDF.

- Source: no link is built in. Open **⚙ Settings** and paste one link that opens a GIA report PDF with its
  report number in it; the portal puts each number you look up in its place. The link is saved only on your
  computer, in `local_settings.json` (excluded from git). `REPORT_PDF_URL` (with `{report}` in it) can be used
  instead; `REPORT_PDF_URL=off` turns lookups off.
- Downloads go one at a time, 1 second apart (`REPORT_PAUSE_SECONDS`), at most 50 numbers per lookup, and each
  PDF is saved in `reports/` (`REPORT_CACHE_DIR`), so a report is downloaded only once.
- A PDF that is not for the requested number is rejected.

### Digital PDFs: no OCR at all
Report PDFs downloaded from GIA (and most lab PDFs) carry a text layer. The portal reads that text directly,
so every value is exact and instant, whichever engine is selected. Scans and photos saved as PDF have no
text layer and go through OCR as usual. (`PDF_TEXT=0` turns this off.)

### How the Windows OCR and PaddleOCR engines read a certificate
1. Each page is straightened (photos are often tilted a few degrees). Windows OCR also gets the page
   upscaled, as PowerToys does, because small print reads better larger.
2. The engine finds words/text boxes; they are chained into lines, so `Label ....... Value` pairs and two-column
   layouts (grading results | proportions) stay together.
3. A label with a missing or implausible value (a lone colour letter "D", clarity read as ".S1") is read a
   second time: leader dots are erased and the label is shown next to its value for context (then the value
   alone, if that still fails). PaddleOCR also re-reads values it is unsure of; Windows OCR reports no
   confidence, so with it only missing or invalid values are re-read.
4. Colour and clarity are always read several times (different scales, a black-and-white copy) and the
   majority wins: one read of "VVS 2" can come back as "VS 2"; several rarely agree on the wrong grade.
   Small screenshots are enlarged first (text under ~10px is unreliable for both engines).
5. Common OCR slips are repaired (`S12`→`SI2`, `WS1`→`VVS1`, `GlA`→`GIA`, `Excelent`→`Excellent`).

Values printed only inside the GIA proportions diagram (table %, depth %, angles on dossier-style reports)
have no labels and are left blank for you to fill in.

Model choice (env vars): `PADDLE_DET_MODEL` (default `PP-OCRv5_server_det`; `PP-OCRv5_mobile_det` is faster,
but misses small text more often), `PADDLE_REC_MODEL` (default `en_PP-OCRv5_mobile_rec`), `PADDLE_PDF_DPI` (200).

### Troubleshooting PaddleOCR
- **`NotImplementedError: ... ConvertPirAttribute2RuntimeAttribute not support ... onednn_instruction.cc`**
  is a PaddlePaddle 3.3 bug on Windows when oneDNN (MKL-DNN) acceleration is on. The portal now runs Paddle
  with oneDNN off (`PADDLE_MKLDNN=0`, the default) and falls back automatically if it ever hits this error.
  If you still see it, install the previous PaddlePaddle release:
  `.venv\Scripts\python -m pip install paddlepaddle==3.2.2`.
- **Slow on CPU** (several seconds per certificate): set `PADDLE_DET_MODEL=PP-OCRv5_mobile_det` before
  `start.bat` (faster, slightly more likely to miss small text), or try `PADDLE_MKLDNN=1` on PaddlePaddle 3.2.x.

## Excel layout
The first columns follow the stock-list format, with short codes:

| Shape | Ct. | Clr | Clrty | C | P | SYM | FLT | Lab | Cert |
|---|---|---|---|---|---|---|---|---|---|
| Round | 0.45 | F | IF | EX | EX | EX | NON | GIA | 1495557172 |

Codes follow Rapaport Trade's "Diamond Fields & Values" list
(https://help.rapaport.com/en/articles/5469769-rapaport-trade-formerly-rapnet-diamond-fields-values):

- Shape: Rapaport shape names, including its table for GIA's square/rectangular brilliants: Rectangular
  Modified Brilliant → Radiant, Cut-Cornered Square Modified Brilliant → Square Radiant, Square Modified
  Brilliant → Princess, Modified Square Brilliant → Cushion Modified, Cushion Brilliant / Cushion Modified
  kept apart, ambiguous Round-Cornered Rectangular Modified Brilliant → Other.
- C / P / SYM: ID, EX, VG, G, F, P. FLT: NON, FNT, VSL, SL, MED, STG, VST, with the fluorescence colour in its
  own column (Flr Color: N, B, W, Y, O, R, G). IGI's online summary gives one "Polish And Symmetry" grade
  (used for both) and "Proportions" instead of a cut grade (used as C).
- Clr: D-Z letters as printed; fancy colours in words ("Fancy Yellowish Brown"), also split into Fancy Color /
  Fancy Intensity / Fancy Overtone.
- Clrty: codes as printed; words are converted: Flawless → FL, Internally Flawless → IF, Loupe Clean → LC.
  A printed grading scale ("CLARITY GRADE: Internally Flawless VVS1 VVS2 …") is never taken as the grade.
- Confirmed conventions: Good is **G** (not GD); IGI's "Proportions" grade is used as **C** when there is no
  cut grade; fancy colours are written in full words in **Clr**; Loupe Clean is **LC**.
- Crown Height % and Pavilion Depth % as well as the angles (IGI prints "Crown Height - Angle 17.5% - 37.8°").
- Ct. is a number shown with two decimals.

After those come the remaining fields: Report Date · Natural / Lab-Grown · Growth Method (CVD/HPHT) ·
Measurements · Length/Width/Depth (mm) · Depth % · Table % · Crown Angle · Pavilion Angle · Girdle · Culet ·
Inscription · Comments · Source File. The on-screen table uses the same layout and codes.

"Append to my Excel…" writes under the matching headers of your own sheet, including these short headers
(Ct., Clr, Clrty, C, P, SYM, FLT, Cert) and Rapaport Trade's accepted column names (Shp, Sz, Colr, Clar,
CutGrade, Finish, Sym, FluorIntensity, FlrColor, CertNum, Meas, Dpth, Tbl, ...), and adds any missing columns
at the right.

**Verify** (next to each GIA/IGI row) and the Cert cell in the exported Excel open the official report
check in your browser: `https://www.gia.edu/report-check?reportno=…` / `https://www.igi.org/verify-your-report/?r=…`.
The portal does not fetch those pages itself: both sites block automated access (Cloudflare/Akamai bot checks).
Automatic lookups need the labs' official APIs: GIA's free [Report Results API](https://gia.edu/report-results-api)
(requires a GIA laboratory client account and an access application in the GIA Client Portal); IGI lists an
"API – Reports & PDFs" service on request.

Key fields (Cert, Shape, Ct., Clr, Clrty) that could not be found are highlighted yellow.
Click 👁 on a row to see the original certificate next to the OCR text and correct anything before exporting.

## Optional: Unlimited-OCR-2 on a GPU server
### 1. Run the OCR model (needs an NVIDIA GPU)
Follow the upstream SGLang instructions (https://github.com/baidu/Unlimited-OCR#sglang) to install the custom
SGLang wheel and start the server, for example on port 10000:
```bash
python -m sglang.launch_server --model-path baidu/Unlimited-OCR-2 --served-model-name Unlimited-OCR-2 \
  --chat-template unlimited-ocr --enable-custom-logit-processor --host 0.0.0.0 --port 10000
```
(use the full flag list from the upstream README for production.)

### 2. Point the portal at it
```bash
pip install -r requirements.txt
OCR_URL=http://<gpu-host>:10000 ./run.sh
```
Open http://localhost:8000. The header dot shows whether the OCR server is reachable.

| Env var | Default | Meaning |
|---|---|---|
| `OCR_BACKEND` | `auto` | `auto`, `paddle` or `unlimited` |
| `OCR_URL` | `http://127.0.0.1:10000` | Unlimited-OCR-2 SGLang server |
| `OCR_CONCURRENCY` | 4 | certificates OCR'd in parallel |
| `OCR_PDF_DPI` | 300 | PDF render resolution |
| `OCR_MAX_PAGES` | 4 | pages per certificate sent to OCR |
| `OCR_TIMEOUT` | 600 | seconds per request |
| `MAX_FILE_MB` | 25 | upload limit |

If the portal runs in the same environment as SGLang, the n-gram repetition guard from the custom wheel is used automatically.

## Samples and tests
`samples/` has two generated GIA-style certificates (a clean scan and a tilted, noisy "photo") to try the portal with.

```bash
python -m pytest -q tests
```
`tests/test_paddle.py::test_pipeline_end_to_end` runs the whole PaddleOCR path on generated photos when
`rapidocr_onnxruntime` is installed (same PP-OCR models packaged with pip; it is only a test aid).
`tests/mock_ocr_server.py` imitates an Unlimited-OCR-2 server for testing that path without a GPU, and
`tests/fake_winrt.py` imitates PyWinRT so the Windows OCR engine is tested off Windows.

## Files
- `app/ocr.py`: engine selection; PDF/image → pages → Unlimited-OCR-2 request → Markdown
- `app/ocr_paddle.py`: PaddleOCR engine, plus the shared page pipeline (deskew, line building, re-reads)
- `app/ocr_windows.py`: Windows OCR engine (`Windows.Media.Ocr` through PyWinRT)
- `app/extract.py`: label/value field extraction and normalisation (add label spellings in `LABELS`)
- `app/excel.py`: new workbook / append to existing sheet (header aliases in `ALIASES`)
- `app/static/index.html`: the portal UI
- `app/vendor/process_unlimitedOCR2.py`: upstream post-processor (MIT, Baidu)

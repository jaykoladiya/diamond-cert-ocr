# Diamond Certificate Portal

Upload diamond grading certificates (GIA, IGI, HRD, AGS, GCAL, ...) as PDFs, scans or phone photos.
The portal reads them with OCR, pulls out the grading fields, shows them in an editable table, and
exports to Excel: either a new workbook, or rows appended to **your own** `.xlsx` (matched by column header).

Two OCR engines:

| Engine | Runs on | When it is used |
|---|---|---|
| **PaddleOCR** (default) | any PC, CPU only | when no Unlimited-OCR server is reachable |
| [Unlimited-OCR-2](https://github.com/baidu/Unlimited-OCR) | NVIDIA GPU with ~16-24 GB+ VRAM, via SGLang | automatically, when its server at `OCR_URL` answers |

The header of the page shows which engine is active. Set `OCR_BACKEND=paddle` or `OCR_BACKEND=unlimited` to force one.

## Quick start on Windows (PaddleOCR, no GPU needed)
1. Install 64-bit Python 3.9-3.13 from python.org (tick "Add python.exe to PATH").
2. Double-click `start.bat`. The first run installs packages into `.venv`; the first certificate
   downloads the OCR models (about 100 MB, once). The browser opens at http://localhost:8000.

Linux / macOS: `pip install -r requirements.txt && ./run.sh`.

### How the PaddleOCR path reads a certificate
1. Each page is straightened (photos are often tilted a few degrees).
2. PaddleOCR finds text boxes; boxes are chained into lines, so `Label ....... Value` pairs and two-column
   layouts (grading results | proportions) stay together.
3. A label with a missing or implausible value (a lone colour letter "D", clarity read as ".S1") is read a
   second time: leader dots are erased and the label is shown next to its value for context.
4. Common OCR slips are repaired (`S12`→`SI2`, `WS1`→`VVS1`, `GlA`→`GIA`, `Excelent`→`Excellent`).

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

## Extracted columns
Lab · Report Number · Report Date · Natural / Lab-Grown · Growth Method (CVD/HPHT) · Shape & Cutting Style ·
Measurements · Length/Width/Depth (mm) · Carat · Color · Clarity · Cut · Polish · Symmetry · Fluorescence ·
Depth % · Table % · Crown Angle · Pavilion Angle · Girdle · Culet · Inscription · Comments · Source File

Key fields (report no., shape, carat, color, clarity) that could not be found are highlighted yellow.
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
`tests/mock_ocr_server.py` imitates an Unlimited-OCR-2 server for testing that path without a GPU.

## Files
- `app/ocr.py`: engine selection; PDF/image → pages → Unlimited-OCR-2 request → Markdown
- `app/ocr_paddle.py`: PaddleOCR engine: deskew, line building, second-pass re-reads
- `app/extract.py`: label/value field extraction and normalisation (add label spellings in `LABELS`)
- `app/excel.py`: new workbook / append to existing sheet (header aliases in `ALIASES`)
- `app/static/index.html`: the portal UI
- `app/vendor/process_unlimitedOCR2.py`: upstream post-processor (MIT, Baidu)

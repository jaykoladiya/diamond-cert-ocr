#!/usr/bin/env bash
# Start the portal. Point OCR_URL at your Unlimited-OCR-2 SGLang server.
set -e
cd "$(dirname "$0")"
export OCR_URL="${OCR_URL:-http://127.0.0.1:10000}"
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"

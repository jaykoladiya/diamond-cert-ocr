"""Stand-in for the Unlimited-OCR-2 SGLang server, for testing the portal without a GPU.

Answers /v1/chat/completions with the canned raw outputs in tests/fixtures/ in turn.
    python tests/mock_ocr_server.py --port 10000
"""
import argparse
import itertools
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request

FIXTURES = sorted((Path(__file__).parent / "fixtures").glob("*.txt"))
cycle = itertools.cycle(FIXTURES)
app = FastAPI()


@app.get("/v1/models")
def models():
    return {"data": [{"id": "Unlimited-OCR-2"}]}


@app.post("/v1/chat/completions")
async def chat(req: Request):
    body = await req.json()
    assert body["messages"][0]["content"][-1]["text"].endswith("Multi page parsing.")
    return {"choices": [{"message": {"content": next(cycle).read_text()}, "finish_reason": "stop"}]}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=10000)
    uvicorn.run(app, host="127.0.0.1", port=ap.parse_args().port)

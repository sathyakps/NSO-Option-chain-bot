import os, json, asyncio
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pathlib import Path

app = FastAPI()

RUN_KEY = os.getenv("RUN_KEY", "sathyakps")  # should be stored as secret
CACHE_FILE = os.getenv("CACHE_FILE", "last_oi.json")

# import your existing function
from nifty_bot import fetch_and_post_once  # adjust if function name differs


@app.get("/health")
def health():
    """Health check endpoint"""
    return {"ok": True}


@app.post("/run")
async def run(request: Request):
    """Trigger the bot manually via HTTP"""
    key = request.headers.get("x-run-key") or request.query_params.get("key")
    if not RUN_KEY or key != RUN_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

    await fetch_and_post_once()
    return {"status": "done"}


@app.get("/last-oi")
def get_last_oi():
    """
    Read and return the contents of last_oi.json.
    If the file does not exist or is invalid JSON, returns a clear message.
    """
    path = Path(CACHE_FILE)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{path} not found")

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return JSONResponse(content=data)
    except json.JSONDecodeError:
        # File exists but content is not valid JSON
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
        return PlainTextResponse(content=raw, media_type="text/plain")

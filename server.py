# server.py
import os, asyncio
from fastapi import FastAPI, HTTPException, Request

app = FastAPI()
RUN_KEY = os.getenv("RUN_KEY", "sathyakps")  # set this as a secret

# import your existing function(s)
from nifty_bot import fetch_and_post_once  # adjust if name differs

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/run")
async def run(request: Request):
    key = request.headers.get("x-run-key") or request.query_params.get("key")
    if not RUN_KEY or key != RUN_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")
    # run your existing job once
    await fetch_and_post_once()
    return {"status": "done"}

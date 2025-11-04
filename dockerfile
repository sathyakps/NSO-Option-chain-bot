# Browsers + deps already included
FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

WORKDIR /app

# App deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir fastapi uvicorn[standard]

# App code
COPY nifty_bot.py server.py /app/

# Runtime env
ENV CACHE_FILE=/data/last_oi.json
ENV RUN_DURING_MARKET_HOURS=true
ENV SINGLE_RUN=true
ENV PORT=8080
EXPOSE 8080

# Ensure data dir exists and start API
CMD bash -lc "mkdir -p /data && uvicorn server:app --host 0.0.0.0 --port ${PORT}"

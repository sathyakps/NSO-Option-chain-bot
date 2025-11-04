FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl wget gnupg \
    libnss3 libx11-6 libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 \
    libasound2 libatk1.0-0 libatk-bridge2.0-0 libatspi2.0-0 \
    libxshmfence1 libgbm1 libpango-1.0-0 libpangocairo-1.0-0 libcairo2 \
    fonts-liberation libdrm2 libxext6 libxfixes3 libxrender1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir fastapi uvicorn[standard]

RUN python -m playwright install --with-deps chromium

COPY nifty_bot.py server.py /app/
ENV CACHE_FILE=/data/last_oi.json
ENV RUN_DURING_MARKET_HOURS=true
ENV SINGLE_RUN=true

# Render listens on $PORT; default uvicorn to 0.0.0.0:$PORT
ENV PORT=8080
EXPOSE 8080
CMD ["bash", "-lc", "mkdir -p /data && uvicorn server:app --host 0.0.0.0 --port ${PORT}"]

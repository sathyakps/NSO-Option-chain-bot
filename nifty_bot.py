#!/usr/bin/env python3
import os
import json
import asyncio
import logging
from datetime import datetime, time as dt_time, timezone, timedelta

# --- Timezone fix for Windows ---
try:
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
except Exception:
    # Fallback if tzdata is missing (Windows)
    IST = timezone(timedelta(hours=5, minutes=30))
# --------------------------------

from playwright.async_api import async_playwright
from telegram import Bot
from telegram.request import HTTPXRequest

"""
Quantsapp CE/PE scraper that posts ΔOI and ΔLTP to Telegram.
Runs once and exits when SINGLE_RUN=true (for CI). Uses IST market hours.
"""

# ---------- CONFIG ----------
QUANTSAPP_URL = os.getenv("QUANTSAPP_URL", "https://web.quantsapp.com/option-chain")
CACHE_FILE = "last_oi.json"
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8438185244:AAGt75e741i4XBsS14EiZAQS4VUZVV1w3RU")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "@nseopn")
FETCH_INTERVAL_SECONDS = int(os.getenv("FETCH_INTERVAL_SECONDS", "900"))
RUN_DURING_MARKET_HOURS = os.getenv("RUN_DURING_MARKET_HOURS", "true").lower() == "true"
MARKET_START = dt_time(9, 15)
MARKET_END = dt_time(15, 30)

IDX = {
    "strike": 6,
    "ce_oi": 3,
    "ce_ltp": 5,
    "pe_ltp": 7,
    "pe_oi": 9,
}

# ----------------------------

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("nifty-bot")

request = HTTPXRequest()
bot = Bot(token=TELEGRAM_TOKEN, request=request)


# ---------- Time helpers ----------
def now_ist():
    return datetime.now(IST)


def in_market_hours():
    if not RUN_DURING_MARKET_HOURS:
        return True
    now = now_ist()
    if now.weekday() >= 5:
        return False
    t = now.time()
    return (MARKET_START <= t <= MARKET_END)


# ---------- Parsing helpers ----------
def parse_num_oi(s):
    if s is None:
        return 0
    t = str(s).strip().upper().replace(",", "")
    if t in ("", "-", "--"):
        return 0
    try:
        if t.endswith("CR"):
            return int(float(t[:-2]) * 1e7)
        if t.endswith("L"):
            return int(float(t[:-1]) * 1e5)
        if t.endswith("K"):
            return int(float(t[:-1]) * 1e3)
        return int(float(t))
    except Exception:
        cleaned = "".join(ch for ch in t if (ch.isdigit() or ch in ".-"))
        try:
            return int(float(cleaned)) if cleaned else 0
        except Exception:
            return 0


def parse_ltp_value(s):
    if s is None:
        return 0.0
    t = str(s).strip()
    if t in ("", "-", "--"):
        return 0.0
    try:
        return float(t.replace(",", ""))
    except Exception:
        cleaned = "".join(ch for ch in t if (ch.isdigit() or ch in ".-"))
        try:
            return float(cleaned) if cleaned else 0.0
        except Exception:
            return 0.0


def human_fmt(n):
    try:
        n = float(n)
    except Exception:
        return str(n)
    n_abs = abs(n)
    if n_abs >= 1e7:
        return f"{n_abs/1e7:.2f}Cr"
    if n_abs >= 1e5:
        return f"{n_abs/1e5:.2f}L"
    if n_abs >= 1e3:
        return f"{n_abs/1e3:.2f}K"
    if n_abs.is_integer():
        return f"{int(n_abs)}"
    return f"{n_abs:.2f}"


def fmt_delta_oi(n):
    sign = "+" if n >= 0 else "-"
    n_abs = abs(n)
    if n_abs >= 1e7:
        return f"{sign}{n_abs/1e7:.2f}Cr"
    if n_abs >= 1e5:
        return f"{sign}{n_abs/1e5:.2f}L"
    if n_abs >= 1e3:
        return f"{sign}{n_abs/1e3:.2f}K"
    return f"{sign}{int(n_abs)}"


def fmt_delta_ltp(n):
    sign = "+" if n >= 0 else "-"
    return f"{sign}{abs(n):.2f}"


# ---------- Cache helpers ----------
def load_last_oi():
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "r") as f:
            store = json.load(f)
    except Exception as e:
        logger.warning("Failed reading cache: %s", e)
        return {}

    migrated = False
    for strike, entry in list(store.items()):
        if not isinstance(entry, dict):
            store[strike] = {"ce": 0, "pe": 0, "ce_ltp": 0.0, "pe_ltp": 0.0}
            migrated = True
            continue
        if "ce_ltp" not in entry:
            entry["ce_ltp"] = float(entry.get("ce_ltp_num", 0.0) or 0.0)
            migrated = True
        if "pe_ltp" not in entry:
            entry["pe_ltp"] = float(entry.get("pe_ltp_num", 0.0) or 0.0)
            migrated = True
        if "ce" not in entry:
            entry["ce"] = int(entry.get("ce_oi", 0) or 0)
            migrated = True
        if "pe" not in entry:
            entry["pe"] = int(entry.get("pe_oi", 0) or 0)
            migrated = True

    if migrated:
        try:
            with open(CACHE_FILE, "w") as f:
                json.dump(store, f)
            logger.info("Migrated old cache")
        except Exception as e:
            logger.warning("Failed writing migrated cache: %s", e)

    return store


def save_last_oi(data_rows):
    store = {}
    for d in data_rows:
        strike = d.get("strike", "<no-strike>")
        ce_ltp_val = float(d.get("ce_ltp", d.get("ce_ltp_num", 0.0) or 0.0))
        pe_ltp_val = float(d.get("pe_ltp", d.get("pe_ltp_num", 0.0) or 0.0))
        store[strike] = {
            "ce": int(d.get("ce_oi", 0) or 0),
            "pe": int(d.get("pe_oi", 0) or 0),
            "ce_ltp": ce_ltp_val,
            "pe_ltp": pe_ltp_val,
        }
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(store, f)
    except Exception as e:
        logger.warning("Failed saving cache: %s", e)


# ---------- Fetching & delta computation ----------
async def fetch_quantsapp_data():
    out = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        logger.info("Navigating to %s", QUANTSAPP_URL)
        await page.goto(QUANTSAPP_URL, timeout=60000)
        await page.wait_for_selector("table tbody tr", timeout=60000)
        await page.wait_for_timeout(1200)
        rows = await page.query_selector_all("table tbody tr")
        logger.info("Found %d rows", len(rows))

        for row in rows:
            try:
                cols = await row.query_selector_all("td")
                if len(cols) <= max(IDX.values()):
                    continue

                strike = (await cols[IDX["strike"]].inner_text()).strip()
                ce_oi_raw = (await cols[IDX["ce_oi"]].inner_text()).strip()
                ce_ltp_raw = (await cols[IDX["ce_ltp"]].inner_text()).strip()
                pe_ltp_raw = (await cols[IDX["pe_ltp"]].inner_text()).strip()
                pe_oi_raw = (await cols[IDX["pe_oi"]].inner_text()).strip()

                ce_oi_num = parse_num_oi(ce_oi_raw)
                pe_oi_num = parse_num_oi(pe_oi_raw)
                ce_ltp_num = parse_ltp_value(ce_ltp_raw)
                pe_ltp_num = parse_ltp_value(pe_ltp_raw)

                out.append({
                    "strike": strike,
                    "ce_oi": ce_oi_num,
                    "pe_oi": pe_oi_num,
                    "ce_oi_raw": ce_oi_raw,
                    "pe_oi_raw": pe_oi_raw,
                    "ce_ltp_raw": ce_ltp_raw,
                    "pe_ltp_raw": pe_ltp_raw,
                    "ce_ltp": float(ce_ltp_num),
                    "pe_ltp": float(pe_ltp_num),
                    "ce_ltp_num": float(ce_ltp_num),
                    "pe_ltp_num": float(pe_ltp_num),
                })
            except Exception as e:
                logger.debug("Row parse failed: %s", e)
                continue

        await browser.close()
    return out


def calc_delta(data_rows, prev_cache):
    result = []
    for d in data_rows:
        try:
            strike = d.get("strike", "<no-strike>")
            prev_entry = prev_cache.get(strike, {})
            ce_old = int(prev_entry.get("ce", 0))
            pe_old = int(prev_entry.get("pe", 0))
            ce_old_ltp = float(prev_entry.get("ce_ltp", 0.0))
            pe_old_ltp = float(prev_entry.get("pe_ltp", 0.0))
            ce_curr_oi = int(d.get("ce_oi", 0))
            pe_curr_oi = int(d.get("pe_oi", 0))
            ce_curr_ltp = float(d.get("ce_ltp", 0.0))
            pe_curr_ltp = float(d.get("pe_ltp", 0.0))
            ce_delta_val = ce_curr_oi - ce_old
            pe_delta_val = pe_curr_oi - pe_old
            ce_ltp_delta = ce_curr_ltp - ce_old_ltp
            pe_ltp_delta = pe_curr_ltp - pe_old_ltp
            d["ce_delta"] = fmt_delta_oi(ce_delta_val)
            d["pe_delta"] = fmt_delta_oi(pe_delta_val)
            d["ce_ltp_change"] = fmt_delta_ltp(ce_ltp_delta)
            d["pe_ltp_change"] = fmt_delta_ltp(pe_ltp_delta)
            result.append(d)
        except Exception as e:
            logger.debug("calc_delta failed: %s", e)
            continue
    return result


# ---------- Formatters & Telegram send ----------
def format_ce_message(rows, top_n=15):
    ts = now_ist().strftime("%Y-%m-%d %H:%M")
    header = f"📈 *NIFTY CE (Call)*\n🕒 {ts} IST\n\n"
    body = "```\nStrike | OI       | ΔOI     | LTP (Δ)\n"
    body += "-------------------------------------\n"
    for d in (rows or [])[:top_n]:
        strike = d.get("strike", "-")
        oi_disp = d.get("ce_oi_raw") or human_fmt(d.get("ce_oi", 0))
        delta = d.get("ce_delta", "+0")
        ltp = d.get("ce_ltp", 0.0)
        ltp_change = d.get("ce_ltp_change", "+0.00")
        body += f"{strike:6} | {oi_disp:8} | {delta:7} | {ltp:6.2f} ({ltp_change})\n"
    body += "```\nSource: web.quantsapp.com"
    return header + body


def format_pe_message(rows, top_n=15):
    ts = now_ist().strftime("%Y-%m-%d %H:%M")
    header = f"📉 *NIFTY PE (Put)*\n🕒 {ts} IST\n\n"
    body = "```\nStrike | OI       | ΔOI     | LTP (Δ)\n"
    body += "-------------------------------------\n"
    for d in (rows or [])[:top_n]:
        strike = d.get("strike", "-")
        oi_disp = d.get("pe_oi_raw") or human_fmt(d.get("pe_oi", 0))
        delta = d.get("pe_delta", "+0")
        ltp = d.get("pe_ltp", 0.0)
        ltp_change = d.get("pe_ltp_change", "+0.00")
        body += f"{strike:6} | {oi_disp:8} | {delta:7} | {ltp:6.2f} ({ltp_change})\n"
    body += "```\nSource: web.quantsapp.com"
    return header + body


async def send_to_telegram(text, parse_mode="Markdown"):
    """Send message safely using the async Telegram Bot."""
    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=text,
            parse_mode=parse_mode
        )
    except Exception as e:
        logger.warning("Telegram send failed: %s", e)


# ---------- Orchestration ----------
async def fetch_and_post_once():
    logger.info("Fetching Quantsapp data at %s ...", now_ist())
    data = await fetch_quantsapp_data()
    if not data:
        logger.warning("No rows fetched.")
        return

    prev = load_last_oi()
    computed = calc_delta(data, prev)
    try:
        computed.sort(key=lambda r: float(r.get("strike", 0)))
    except Exception:
        pass

    save_last_oi(computed)
    ce_msg = format_ce_message(computed)
    pe_msg = format_pe_message(computed)
    await send_to_telegram(ce_msg)
    await asyncio.sleep(0.5)
    await send_to_telegram(pe_msg)
    logger.info("Posted CE and PE messages to Telegram.")


if __name__ == "__main__":
    try:
        if os.getenv("SINGLE_RUN", "true").lower() == "true":
            if in_market_hours():
                asyncio.run(fetch_and_post_once())
            else:
                logger.info("Outside market hours. Skipping this run.")
        # else:
        #     asyncio.run(fetch_and_post_once())
    except KeyboardInterrupt:
        logger.info("Interrupted by user, exiting.")

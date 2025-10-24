import os
import requests
from datetime import datetime, time, timezone
import pytz
import html
import json

NSE_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.nseindia.com/',
    'Origin': 'https://www.nseindia.com'
}

IST = pytz.timezone("Asia/Kolkata")

def in_market_hours_ist(dt_utc: datetime) -> bool:
    now_ist = dt_utc.astimezone(IST)
    if now_ist.weekday() > 4:  # Mon-Fri only
        return False
    start = time(9, 15)
    end   = time(15, 30)
    t = now_ist.time()
    return start <= t <= end

def setup_session():
    s = requests.Session()
    s.headers.update(NSE_HEADERS)
    try:
        s.get("https://www.nseindia.com/", timeout=10)
    except requests.RequestException:
        pass
    return s

def fetch_option_chain(session):
    url = "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY"
    r = session.get(url, timeout=15)
    r.raise_for_status()
    return r.json()

def get_underlying(data):
    return data['records']['underlyingValue']

def find_atm_strike(underlying, step=50):
    return round(underlying / step) * step

def filter_grid(data, atm, strikes_each_side=6):
    rows = []
    lo = atm - strikes_each_side * 50
    hi = atm + strikes_each_side * 50
    for rec in data['records']['data']:
        sp = rec.get('strikePrice')
        if sp is None or sp < lo or sp > hi:
            continue
        CE = rec.get('CE', {})
        PE = rec.get('PE', {})
        rows.append({
            'strike': sp,
            'call_oi': CE.get('openInterest', 0) or 0,
            'call_ltp': CE.get('lastPrice', 0.0) or 0.0,
            'put_ltp': PE.get('lastPrice', 0.0) or 0.0,
            'put_oi': PE.get('openInterest', 0) or 0,
        })
    rows.sort(key=lambda x: x['strike'])
    return rows

def fmt_num(n: int) -> str:
    if n >= 10_000_000:  # Cr
        return f"{n/10_000_000:.1f}Cr"
    if n >= 100_000:     # L
        return f"{n/100_000:.1f}L"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(int(n))

def build_html(rows, underlying, atm):
    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
    header = (
        f"<b>🏛️ NIFTY Option Chain Update</b>\n"
        f"⏰ <b>Time:</b> {html.escape(now)}\n"
        f"📊 <b>Underlying:</b> {underlying:.2f}\n"
        f"🎯 <b>ATM Strike:</b> {atm}\n\n"
    )
    table_lines = []
    table_lines.append(f"{'Strike':<8} {'Call OI':<12} {'Call LTP':<10} {'Put LTP':<10} {'Put OI':<12}")
    table_lines.append(f"{'-'*6:<8} {'-'*8:<12} {'-'*8:<10} {'-'*7:<10} {'-'*7:<12}")
    for r in rows:
        strike = f"*{r['strike']}*" if r['strike'] == atm else f"{r['strike']}"
        line = f"{strike:<8} {fmt_num(r['call_oi']):<12} {r['call_ltp']:<10.1f} {r['put_ltp']:<10.1f} {fmt_num(r['put_oi']):<12}"
        table_lines.append(line)
    total_call_oi = fmt_num(sum(r['call_oi'] for r in rows))
    total_put_oi = fmt_num(sum(r['put_oi'] for r in rows))
    footer = f"\n📈 <b>Total Call OI:</b> {total_call_oi}\n📉 <b>Total Put OI:</b> {total_put_oi}\n"
    return header + "<pre>" + html.escape("\n".join(table_lines)) + "</pre>" + footer

def send_telegram_html(bot_token: str, chat_id_or_username: str, html_text: str):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id_or_username,
        "text": html_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    r = requests.post(url, json=payload, timeout=15)
    r.raise_for_status()
    return r.json()

def main():
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id  = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not bot_token or not chat_id:
        print("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
        return

    now_utc = datetime.now(timezone.utc)
    if not in_market_hours_ist(now_utc):
        print("Outside market hours (IST). Exiting.")
        return

    s = setup_session()
    try:
        data = fetch_option_chain(s)
        underlying = get_underlying(data)
        atm = find_atm_strike(underlying)
        rows = filter_grid(data, atm, strikes_each_side=6)
        msg = build_html(rows, underlying, atm)
        resp = send_telegram_html(bot_token, chat_id, msg)
        print("Sent:", json.dumps(resp)[:200], "...")
    except Exception as e:
        print("Error:", repr(e))

if __name__ == "__main__":
    main()

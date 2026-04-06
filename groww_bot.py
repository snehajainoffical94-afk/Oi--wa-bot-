"""
OI Flow Bot — Groww Trade API
Sends Nifty + Bank Nifty monthly expiry OI flow to Telegram.
"""

import os, sys, json, requests, csv, io, traceback
from datetime import date, datetime
from dotenv import load_dotenv

load_dotenv()

GROWW_TOKEN      = os.getenv("GROWW_API_TOKEN", "")
GROWW_SECRET     = os.getenv("GROW_API_SECRET", "")
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
STATE_FILE       = "state/groww_oi_state.json"

os.makedirs("state", exist_ok=True)


# ── Self-diagnostics ─────────────────────────────────────────────────────────

def check_env():
    """Check all required env vars are set. Sends Telegram alert if not."""
    missing = []
    if not GROWW_TOKEN:   missing.append("GROWW_API_TOKEN")
    if not GROWW_SECRET:  missing.append("GROW_API_SECRET")
    if not TELEGRAM_TOKEN: missing.append("TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_CHAT_ID: missing.append("TELEGRAM_CHAT_ID")
    if missing:
        msg = f"OI Bot FATAL: Missing env vars: {', '.join(missing)}\nAdd them to GitHub Secrets."
        print(f"[FATAL] {msg}")
        if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
            send_telegram(f"⛔ {msg}")
        sys.exit(1)


# ── Auth ──────────────────────────────────────────────────────────────────────

def init_groww():
    """Two-step Groww auth. Returns authenticated GrowwAPI instance."""
    from growwapi import GrowwAPI
    try:
        access_token = GrowwAPI.get_access_token(api_key=GROWW_TOKEN, secret=GROWW_SECRET)
        print(f"[AUTH] OK")
        return GrowwAPI(access_token)
    except Exception as e:
        msg = f"Groww auth failed: {e}"
        print(f"[FATAL] {msg}")
        send_telegram(f"⛔ {msg}\n\nPossible fixes:\n1. Regenerate GROWW_API_TOKEN on Groww dashboard\n2. Check GROW_API_SECRET is correct\n3. Your 45-day trial may have expired")
        sys.exit(1)


# ── Expiry (from instrument CSV) ─────────────────────────────────────────────

_expiry_cache = {}

def _load_expiries():
    """Download instrument CSV and extract expiry dates per underlying."""
    if _expiry_cache:
        return
    from growwapi import GrowwAPI
    print("[INST] Downloading instrument list...")
    r = requests.get(GrowwAPI.INSTRUMENT_CSV_URL, timeout=60)
    r.raise_for_status()
    reader = csv.DictReader(io.StringIO(r.text))
    for row in reader:
        sym = row.get("underlying_symbol", "")
        exp = row.get("expiry_date", "")
        if sym and exp:
            _expiry_cache.setdefault(sym, set()).add(exp)
    print(f"[INST] Loaded expiries for {len(_expiry_cache)} underlyings")


def get_monthly_expiry(symbol: str) -> str:
    """Pick the nearest monthly expiry (last expiry in the current/next month)."""
    _load_expiries()
    today = date.today()
    raw = _expiry_cache.get(symbol, set())

    parsed = []
    for e in raw:
        try:
            d = datetime.strptime(e, "%Y-%m-%d").date()
            if d >= today:
                parsed.append((d, e))
        except ValueError:
            continue

    if not parsed:
        raise ValueError(f"No future expiries for {symbol}")

    parsed.sort()
    target_month = parsed[0][0].month
    monthly_candidates = [(d, e) for d, e in parsed if d.month == target_month]
    return monthly_candidates[-1][1]


# ── Spot price ────────────────────────────────────────────────────────────────

def get_spot(groww, symbol: str) -> float:
    """Fetch live spot from Groww LTP API."""
    resp = groww.get_ltp(
        exchange_trading_symbols=(f"NSE_{symbol}",),
        segment=groww.SEGMENT_CASH,
    )
    key = f"NSE_{symbol}"
    if key in resp:
        val = resp[key]
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, dict) and "ltp" in val:
            return float(val["ltp"])
    raise ValueError(f"Could not extract LTP for {symbol}: {resp}")


# ── State ─────────────────────────────────────────────────────────────────────

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            data = json.load(f)
            print(f"[STATE] Loaded previous state ({len(data)} symbols)")
            return data
    print("[STATE] No previous state — first run, OI changes will be 0")
    return {}


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)
    print(f"[STATE] Saved ({len(state)} symbols)")


# ── Fetch & Process ───────────────────────────────────────────────────────────

def process(groww, symbol: str, state: dict) -> dict:
    expiry = get_monthly_expiry(symbol)
    spot   = get_spot(groww, symbol)
    print(f"[{symbol}] Spot: {spot} | Expiry: {expiry}")

    resp = groww.get_option_chain(
        exchange=groww.EXCHANGE_NSE,
        underlying=symbol,
        expiry_date=expiry,
    )

    strikes = resp.get("strikes", {})
    print(f"[{symbol}] {len(strikes)} strikes in chain")

    if not strikes:
        raise ValueError(f"Empty option chain for {symbol} expiry {expiry}")

    prev = state.get(symbol, {})
    has_prev = len(prev) > 0
    rows = []

    for strike_key, data in strikes.items():
        try:
            strike = int(float(strike_key))
        except (ValueError, TypeError):
            continue

        if not isinstance(data, dict):
            continue

        ce = data.get("CE", {})
        pe = data.get("PE", {})

        ce_oi = int(ce.get("open_interest", 0) or 0)
        pe_oi = int(pe.get("open_interest", 0) or 0)

        if ce_oi == 0 and pe_oi == 0:
            continue

        key        = str(strike)
        prev_ce_oi = prev.get(key, {}).get("ce_oi", ce_oi)
        prev_pe_oi = prev.get(key, {}).get("pe_oi", pe_oi)

        rows.append({
            "strike":       strike,
            "ce_oi":        ce_oi,
            "pe_oi":        pe_oi,
            "ce_oi_change": ce_oi - prev_ce_oi,
            "pe_oi_change": pe_oi - prev_pe_oi,
        })

    if not rows:
        raise ValueError(f"No strikes with OI for {symbol} expiry {expiry}")

    new_state = {str(r["strike"]): {"ce_oi": r["ce_oi"], "pe_oi": r["pe_oi"]} for r in rows}
    state[symbol] = new_state

    print(f"[{symbol}] {len(rows)} strikes with OI | Previous state: {'yes' if has_prev else 'no (first run)'}")
    return {
        "symbol":   symbol,
        "spot":     spot,
        "expiry":   expiry,
        "rows":     sorted(rows, key=lambda x: x["strike"]),
        "has_prev": has_prev,
    }


# ── Format ────────────────────────────────────────────────────────────────────

def _L(val: int) -> str:
    return f"{val / 100000:.1f}L"


def format_message(data: dict) -> str:
    symbol = data["symbol"]
    spot   = data["spot"]
    expiry = data["expiry"]
    rows   = data["rows"]
    now    = datetime.now().strftime("%H:%M")
    label  = "BANK NIFTY" if symbol == "BANKNIFTY" else "NIFTY"

    ce_writing = sorted(
        [r for r in rows if r["ce_oi_change"] > 0 and r["strike"] >= spot],
        key=lambda x: x["ce_oi_change"], reverse=True
    )[:2]

    pe_writing = sorted(
        [r for r in rows if r["pe_oi_change"] > 0 and r["strike"] <= spot],
        key=lambda x: x["pe_oi_change"], reverse=True
    )[:2]

    unwind_candidates = []
    for r in rows:
        if r["ce_oi_change"] < 0:
            unwind_candidates.append({"strike": r["strike"], "type": "CE", "chg": r["ce_oi_change"]})
        if r["pe_oi_change"] < 0:
            unwind_candidates.append({"strike": r["strike"], "type": "PE", "chg": r["pe_oi_change"]})
    unwind = min(unwind_candidates, key=lambda x: x["chg"]) if unwind_candidates else None

    total_ce = sum(r["ce_oi"] for r in rows) or 1
    total_pe = sum(r["pe_oi"] for r in rows)
    pcr = round(total_pe / total_ce, 2)

    total_ce_chg = sum(r["ce_oi_change"] for r in rows if r["ce_oi_change"] > 0) or 1
    total_pe_chg = sum(r["pe_oi_change"] for r in rows if r["pe_oi_change"] > 0)
    day_pcr = round(total_pe_chg / total_ce_chg, 2) if total_ce_chg != 1 else "N/A"

    support = pe_writing[0]["strike"] if pe_writing else 0
    resistance = ce_writing[0]["strike"] if ce_writing else 0
    if len(ce_writing) > 1 and ce_writing[1]["strike"] < ce_writing[0]["strike"]:
        resistance = ce_writing[1]["strike"]

    if pcr >= 1.2:
        sentiment = "🟢 Bullish"
    elif pcr <= 0.8:
        sentiment = "🔴 Bearish"
    else:
        sentiment = "⚪ Neutral"

    lines = [
        f"*{label} — OI FLOW (MONTHLY)*",
        f"{now} | Spot: *{spot:,.0f}* | Expiry: {expiry}",
        "",
        "*Call Writing (Resistance)*",
    ]

    if ce_writing:
        for r in ce_writing:
            lines.append(f"🔴 {r['strike']:,} → +{_L(r['ce_oi_change'])}")
    else:
        lines.append("No significant call writing")

    lines += ["", "*Put Writing (Support)*"]

    if pe_writing:
        for r in pe_writing:
            lines.append(f"🟢 {r['strike']:,} → +{_L(r['pe_oi_change'])}")
    else:
        lines.append("No significant put writing")

    lines += [
        "",
        "*PCR*",
        f"Current: *{pcr}* | Day Change: *{day_pcr}*",
    ]

    if unwind:
        lines += [
            "",
            "*Unwinding*",
            f"⚠️ {unwind['strike']:,} {unwind['type']} → -{_L(abs(unwind['chg']))}",
        ]

    lines += [
        "",
        "*View*",
        f"🟢 Support *{support:,}* | 🔴 Resistance *{resistance:,}*",
        f"{sentiment}",
    ]

    if not data.get("has_prev"):
        lines += ["", "_First run — OI changes will show from next update_"]

    return "\n".join(lines)


# ── Telegram ──────────────────────────────────────────────────────────────────

def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    r = requests.post(url, json={
        "chat_id":    TELEGRAM_CHAT_ID,
        "text":       text,
        "parse_mode": "Markdown",
    }, timeout=10)
    r.raise_for_status()
    print(f"[TG] Sent")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    check_env()
    groww = init_groww()
    state = load_state()

    for symbol in ["NIFTY", "BANKNIFTY"]:
        try:
            data    = process(groww, symbol, state)
            message = format_message(data)
            send_telegram(message)
            print(f"[OK] {symbol} sent")
        except Exception as e:
            err_detail = traceback.format_exc()
            print(f"[ERR] {symbol}:\n{err_detail}")

            # Send a helpful error to Telegram
            hint = ""
            err_str = str(e).lower()
            if "forbidden" in err_str or "403" in err_str:
                hint = "\nHint: Groww token may have expired. Regenerate on Groww dashboard."
            elif "timeout" in err_str:
                hint = "\nHint: Groww API is slow/down. Will retry next hour."
            elif "authentication" in err_str or "401" in err_str:
                hint = "\nHint: Groww credentials invalid. Check GROWW_API_TOKEN and GROW_API_SECRET."
            elif "expir" in err_str:
                hint = "\nHint: No expiry dates found. Market may be on holiday."

            try:
                send_telegram(f"⚠️ OI Bot error ({symbol}): {str(e)[:200]}{hint}")
            except Exception:
                pass

    save_state(state)
    print("[DONE]")

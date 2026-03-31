"""
Angel One SmartAPI — Options Chain OI Fetcher

Flow:
  1. Download instrument master (cached per day)
  2. Find nearest expiry tokens for NIFTY / BANKNIFTY
  3. Batch-call Quote API (max 50 tokens/call) → get OI per strike
  4. Return structured list for processor.py
"""

import requests
import logging
import json
import os
from datetime import date, timedelta, datetime
from auth import auth_headers

logger = logging.getLogger(__name__)

BASE_URL    = "https://apiconnect.angelone.in"
MASTER_URL  = "https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json"
MASTER_FILE = "state/instrument_master.json"
MASTER_DATE = "state/master_date.txt"

os.makedirs("state", exist_ok=True)


# ── Instrument Master ────────────────────────────────────────────────────────

def _download_master() -> list:
    logger.info("Downloading Angel One instrument master...")
    r = requests.get(MASTER_URL, timeout=30)
    r.raise_for_status()
    data = r.json()
    with open(MASTER_FILE, "w") as f:
        json.dump(data, f)
    with open(MASTER_DATE, "w") as f:
        f.write(str(date.today()))
    logger.info(f"Master downloaded. {len(data)} instruments.")
    return data


def get_master() -> list:
    """Return cached master; re-download if stale (new day)."""
    today = str(date.today())
    if os.path.exists(MASTER_FILE) and os.path.exists(MASTER_DATE):
        with open(MASTER_DATE) as f:
            cached_date = f.read().strip()
        if cached_date == today:
            with open(MASTER_FILE) as f:
                return json.load(f)
    return _download_master()


# ── Expiry Helpers ────────────────────────────────────────────────────────────

def nearest_expiry_date(symbol: str) -> date:
    """Returns nearest expiry as a date object."""
    today      = date.today()
    target_day = 3 if symbol == "NIFTY" else 2   # Thu=3, Wed=2
    delta      = (target_day - today.weekday()) % 7
    if delta == 0:
        delta = 7
    return today + timedelta(days=delta)


def _format_expiry_master(d: date) -> str:
    """Angel One master uses expiry like '21OCT2021'."""
    return d.strftime("%d%b%Y").upper()


# ── Token Lookup ──────────────────────────────────────────────────────────────

def get_nearest_expiry_from_master(symbol: str, master: list) -> str:
    """Pick the nearest future expiry for a symbol from actual master data."""
    today = date.today()
    expiries = set(
        inst["expiry"]
        for inst in master
        if inst.get("name") == symbol
        and inst.get("instrumenttype") == "OPTIDX"
        and inst.get("exch_seg") == "NFO"
    )
    future = []
    for e in expiries:
        try:
            d = datetime.strptime(e, "%d%b%Y").date()
            if d >= today:
                future.append((d, e))
        except Exception:
            continue
    if not future:
        raise ValueError(f"No future expiry found in master for {symbol}")
    return sorted(future)[0][1]   # nearest expiry string


def get_option_tokens(symbol: str, master: list) -> list:
    """
    Returns list of dicts:
      {token, strike, option_type, expiry_str}
    for all strikes of the nearest available expiry.
    """
    expiry_str = get_nearest_expiry_from_master(symbol, master)

    tokens = []
    for inst in master:
        if (
            inst.get("exch_seg") == "NFO"
            and inst.get("instrumenttype") == "OPTIDX"
            and inst.get("name") == symbol
            and inst.get("expiry") == expiry_str
        ):
            try:
                strike = float(inst["strike"]) / 100   # Angel One stores strike × 100
                tokens.append({
                    "token":       inst["token"],
                    "strike":      int(strike),
                    "option_type": inst["symbol"][-2:],  # CE or PE
                    "expiry":      expiry_str,
                })
            except Exception:
                continue

    logger.info(f"{symbol} ({expiry_str}): {len(tokens)} option tokens found.")
    return tokens


# ── Quote API (OI fetch) ──────────────────────────────────────────────────────

def _batch_quote(tokens: list[str]) -> list:
    """Fetch FULL quote for up to 50 NFO tokens."""
    headers = auth_headers()
    body    = {"mode": "FULL", "exchangeTokens": {"NFO": tokens}}
    r = requests.post(
        f"{BASE_URL}/rest/secure/angelbroking/market/v1/quote/",
        json=body,
        headers=headers,
        timeout=20
    )
    r.raise_for_status()
    resp = r.json()
    if not resp.get("status"):
        raise ValueError(f"Quote API error: {resp.get('message')}")
    return resp["data"].get("fetched", [])


def fetch_option_chain(symbol: str) -> list:
    """
    Main entry point.
    Returns list of dicts with strike, CE OI/change, PE OI/change.
    """
    master     = get_master()
    all_tokens = get_option_tokens(symbol, master)

    if not all_tokens:
        raise ValueError(f"No tokens found for {symbol}. Check expiry or instrument master.")

    # Split into CE/PE maps
    token_list = [t["token"] for t in all_tokens]
    token_meta = {t["token"]: t for t in all_tokens}

    # Batch fetch (50 per call)
    quotes = []
    for i in range(0, len(token_list), 50):
        batch   = token_list[i:i + 50]
        fetched = _batch_quote(batch)
        quotes.extend(fetched)
        logger.info(f"{symbol} batch {i//50 + 1}: {len(fetched)} quotes fetched.")

    # Build strike-keyed dict
    strike_map = {}
    for q in quotes:
        token  = str(q.get("symbolToken", ""))
        meta   = token_meta.get(token)
        if not meta:
            continue
        strike = meta["strike"]
        opt    = meta["option_type"]

        if strike not in strike_map:
            strike_map[strike] = {
                "strike": strike,
                "ce_oi": 0, "ce_oi_change": 0,
                "ce_bid": 0.0, "ce_ask": 0.0,
                "pe_oi": 0, "pe_oi_change": 0,
                "pe_bid": 0.0, "pe_ask": 0.0,
            }

        oi     = int(q.get("opnInterest", 0) or 0)
        oi_chg = int(q.get("netchangeInOI", 0) or 0)
        bid    = float(q.get("bidPrice1", 0) or 0)
        ask    = float(q.get("askPrice1", 0) or 0)

        if opt == "CE":
            strike_map[strike].update({"ce_oi": oi, "ce_oi_change": oi_chg, "ce_bid": bid, "ce_ask": ask})
        else:
            strike_map[strike].update({"pe_oi": oi, "pe_oi_change": oi_chg, "pe_bid": bid, "pe_ask": ask})

    result = sorted(strike_map.values(), key=lambda x: x["strike"])
    logger.info(f"{symbol}: {len(result)} strikes processed.")
    return result

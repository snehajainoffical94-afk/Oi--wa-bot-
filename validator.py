"""
Data Validator — Auto-checks fetched data for sanity.
Runs after every fetch, flags issues via Telegram if detected.
No human intervention needed.
"""
import logging
import requests
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

# Known rough ranges (updated periodically)
SPOT_RANGES = {
    "NIFTY":     (18_000, 30_000),
    "BANKNIFTY": (38_000, 65_000),
}


def validate_spot(symbol: str, spot: float) -> list:
    """Check if spot price is within plausible range."""
    errors = []
    lo, hi = SPOT_RANGES.get(symbol, (0, 999999))
    if not lo <= spot <= hi:
        errors.append(f"SPOT OUT OF RANGE: {symbol} spot={spot:,.0f} (expected {lo:,}–{hi:,})")
    if spot == 0:
        errors.append(f"SPOT IS ZERO: {symbol}")
    return errors


def validate_chain(records: list, symbol: str, spot: float) -> list:
    """Check options chain data for anomalies."""
    errors = []

    if len(records) < 20:
        errors.append(f"TOO FEW STRIKES: {symbol} has only {len(records)} strikes (expected 50+)")

    # Check that at least some strikes have non-zero OI
    oi_count = sum(1 for r in records if r["ce_oi"] > 0 or r["pe_oi"] > 0)
    if oi_count < 10:
        errors.append(f"LOW OI COUNT: Only {oi_count} strikes have any OI for {symbol}")

    # Check ATM region has data
    gap = 50 if symbol == "NIFTY" else 100
    atm = round(spot / gap) * gap
    atm_strikes = [r for r in records if abs(r["strike"] - atm) <= 5 * gap]
    if not atm_strikes:
        errors.append(f"NO ATM DATA: No strikes near ATM {atm} for {symbol}")

    atm_oi = sum(r["ce_oi"] + r["pe_oi"] for r in atm_strikes)
    if atm_oi == 0:
        errors.append(f"ZERO OI AT ATM: All strikes near {atm} have 0 OI for {symbol}")

    # Check for stale data (all OI changes exactly 0 during market hours)
    now = datetime.now(IST)
    is_market = (now.weekday() < 5
                 and 9 <= now.hour < 15
                 or (now.hour == 15 and now.minute <= 30)
                 or (now.hour == 9 and now.minute >= 15))
    if is_market:
        all_zero = all(r["ce_oi_change"] == 0 and r["pe_oi_change"] == 0 for r in records)
        if all_zero:
            errors.append(f"STALE DATA WARNING: All OI changes are 0 during market hours for {symbol}")

    return errors


def validate_pcr(pcr: float, symbol: str) -> list:
    """PCR sanity check — extreme values may indicate bad data."""
    errors = []
    if pcr > 5.0:
        errors.append(f"EXTREME PCR: {symbol} PCR={pcr} (unusually high, check PE/CE OI)")
    if pcr < 0.1:
        errors.append(f"EXTREME PCR: {symbol} PCR={pcr} (unusually low, check PE/CE OI)")
    return errors


def run_validation(symbol: str, spot: float, records: list, processed: dict) -> list:
    """
    Run all validations. Returns list of error strings.
    Empty list = data is clean.
    """
    errors = []
    errors += validate_spot(symbol, spot)
    errors += validate_chain(records, symbol, spot)
    errors += validate_pcr(processed.get("current_pcr", 0), symbol)
    return errors


def format_validation_alert(errors: list) -> str:
    """Format validation errors into a Telegram message."""
    lines = [
        "⚠️ *DATA VALIDATION ALERT*",
        "",
    ]
    for e in errors:
        lines.append(f"• {e}")
    lines += [
        "",
        "_Bot will continue sending data but please verify manually._",
    ]
    return "\n".join(lines)

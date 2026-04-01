"""
OI Flow Processor — Monthly Expiry Only
Computes all trader-relevant metrics from raw strike records.
"""
import logging
from config import TOP_WALLS

logger = logging.getLogger(__name__)

MIN_MEANINGFUL = 50_000    # 0.5L — below this is noise
MIN_UNWIND     = 50_000    # 0.5L — minimum to flag as unwinding


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_atm(spot: float, symbol: str) -> int:
    gap = 50 if symbol == "NIFTY" else 100
    return round(spot / gap) * gap


def _lakhs(x: int) -> float:
    return round(x / 100_000, 1)


# ── Core Metric Functions ─────────────────────────────────────────────────────

def get_major_call_writing_zones(records: list, atm: int, n: int = TOP_WALLS) -> list:
    """Top N CE writing strikes ABOVE ATM with meaningful positive day OI change."""
    candidates = [
        r for r in records
        if r["strike"] >= atm and r["ce_oi_change"] >= MIN_MEANINGFUL
    ]
    if not candidates:
        # Fallback: relax threshold, still above ATM
        candidates = [r for r in records if r["strike"] >= atm and r["ce_oi_change"] > 0]
    return sorted(candidates, key=lambda x: x["ce_oi_change"], reverse=True)[:n]


def get_major_put_writing_zones(records: list, atm: int, n: int = TOP_WALLS) -> list:
    """Top N PE writing strikes BELOW ATM with meaningful positive day OI change."""
    candidates = [
        r for r in records
        if r["strike"] <= atm and r["pe_oi_change"] >= MIN_MEANINGFUL
    ]
    if not candidates:
        candidates = [r for r in records if r["strike"] <= atm and r["pe_oi_change"] > 0]
    return sorted(candidates, key=lambda x: x["pe_oi_change"], reverse=True)[:n]


def get_max_change_today(records: list) -> dict:
    """Strike with single highest CE day change and single highest PE day change."""
    max_ce = max(records, key=lambda x: x["ce_oi_change"])
    max_pe = max(records, key=lambda x: x["pe_oi_change"])
    return {"ce": max_ce, "pe": max_pe}


def get_total_oi_change(records: list) -> tuple[int, int]:
    """Sum of all CE and PE day OI changes across monthly chain."""
    total_ce = sum(r["ce_oi_change"] for r in records)
    total_pe = sum(r["pe_oi_change"] for r in records)
    return total_ce, total_pe


def compute_current_pcr(records: list) -> float:
    """total_pe_oi / total_ce_oi across all monthly strikes."""
    total_ce = sum(r["ce_oi"] for r in records) or 1
    total_pe = sum(r["pe_oi"] for r in records)
    return round(total_pe / total_ce, 2)


def compute_day_change_pcr(total_pe_day: int, total_ce_day: int):
    """Day change PCR. Returns None if denominator is zero or near zero."""
    if abs(total_ce_day) < MIN_MEANINGFUL:
        return None
    return round(total_pe_day / total_ce_day, 2)


def detect_meaningful_unwinding(records: list, atm: int) -> dict:
    """
    Find biggest CE and PE unwinding (most negative day OI change).
    Only return if change crosses -MIN_UNWIND threshold.
    """
    ce_candidate = min(records, key=lambda x: x["ce_oi_change"])
    pe_candidate = min(records, key=lambda x: x["pe_oi_change"])

    return {
        "ce": ce_candidate if ce_candidate["ce_oi_change"] < -MIN_UNWIND else None,
        "pe": pe_candidate if pe_candidate["pe_oi_change"] < -MIN_UNWIND else None,
    }


def find_strongest_support_resistance(
    call_zones: list, put_zones: list, records: list, atm: int, symbol: str
) -> dict:
    """
    Near support = nearest PUT writing zone below ATM (highest strike in put_zones).
    Near resistance = nearest CALL writing zone above ATM (lowest strike in call_zones).
    Fallback to highest OI if no writing zones found.
    """
    gap = 50 if symbol == "NIFTY" else 100

    if put_zones:
        support = max(put_zones, key=lambda x: x["strike"])
    else:
        below = [r for r in records if r["strike"] <= atm]
        support = max(below, key=lambda x: x["pe_oi"]) if below else None

    if call_zones:
        resistance = min(call_zones, key=lambda x: x["strike"])
    else:
        above = [r for r in records if r["strike"] >= atm]
        resistance = min(above, key=lambda x: x["ce_oi"]) if above else None

    return {
        "support":    support["strike"] if support else atm - gap * 5,
        "resistance": resistance["strike"] if resistance else atm + gap * 5,
    }


def derive_market_view(
    total_ce_day: int,
    total_pe_day: int,
    current_pcr: float,
    day_change_pcr,
    unwind: dict,
    support: int,
    resistance: int,
    spot: float,
) -> dict:
    """
    Composite bias using all available signals.
    Returns bias label + range bounds + breakout levels.
    """
    score = 0

    # Flow signal
    if total_pe_day > total_ce_day:
        score += 1
    elif total_ce_day > total_pe_day:
        score -= 1

    # Current PCR
    if current_pcr >= 1.2:   score += 1
    elif current_pcr < 0.8:  score -= 1

    # Day change PCR
    if day_change_pcr is not None:
        if day_change_pcr > 1.2:   score += 1
        elif day_change_pcr < 0.8: score -= 1

    # Unwinding signals
    if unwind["ce"]:   score += 1   # resistance weakening = bullish lean
    if unwind["pe"]:   score -= 1   # support weakening = bearish lean

    if   score >= 2:  bias = "Slight Bullish"
    elif score == 1:  bias = "Mild Bullish"
    elif score == 0:  bias = "Rangebound / Neutral"
    elif score == -1: bias = "Mild Bearish"
    else:             bias = "Slight Bearish"

    return {
        "bias":       bias,
        "support":    support,
        "resistance": resistance,
        "range_low":  support,
        "range_high": resistance,
    }


# ── Main Entry ────────────────────────────────────────────────────────────────

def process_chain(records: list, symbol: str, spot: float = None) -> dict:
    """
    Input : list of strike dicts from fetcher.py (monthly expiry)
    Output: structured dict for formatter.py
    """
    if not records:
        raise ValueError(f"Empty records for {symbol}")
    if spot is None:
        raise ValueError(f"Spot price missing for {symbol}")

    atm = get_atm(spot, symbol)
    logger.info(f"{symbol} spot={spot} ATM={atm}")

    call_zones  = get_major_call_writing_zones(records, atm)
    put_zones   = get_major_put_writing_zones(records, atm)
    max_change  = get_max_change_today(records)
    total_ce_day, total_pe_day = get_total_oi_change(records)
    current_pcr = compute_current_pcr(records)
    day_pcr     = compute_day_change_pcr(total_pe_day, total_ce_day)
    unwind      = detect_meaningful_unwinding(records, atm)
    sr          = find_strongest_support_resistance(call_zones, put_zones, records, atm, symbol)
    view        = derive_market_view(
                      total_ce_day, total_pe_day, current_pcr,
                      day_pcr, unwind, sr["support"], sr["resistance"], spot
                  )

    # Keep ce/pe walls for compatibility with spike_detector
    gap = 50 if symbol == "NIFTY" else 100
    ce_candidates = [r for r in records if r["strike"] >= atm]
    pe_candidates = [r for r in records if r["strike"] <= atm]
    ce_walls = sorted(ce_candidates, key=lambda x: x["ce_oi"], reverse=True)[:3]
    pe_walls = sorted(pe_candidates, key=lambda x: x["pe_oi"], reverse=True)[:3]

    return {
        "symbol":         symbol,
        "spot":           spot,
        "atm":            atm,
        # new metrics
        "call_zones":     call_zones,
        "put_zones":      put_zones,
        "max_change":     max_change,
        "total_ce_day":   total_ce_day,
        "total_pe_day":   total_pe_day,
        "current_pcr":    current_pcr,
        "day_change_pcr": day_pcr,
        "unwinding":      unwind,
        "view":           view,
        # legacy (spike detector uses these)
        "ce_walls":       ce_walls,
        "pe_walls":       pe_walls,
        "overall_pcr":    current_pcr,
        "overall_bias":   view["bias"],
        "battle_zone":    [],   # removed — no longer shown
    }

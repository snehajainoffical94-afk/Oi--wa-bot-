import logging
from config import STRIKE_WINDOW, TOP_WALLS

logger = logging.getLogger(__name__)


def get_atm(spot: float, symbol: str) -> int:
    gap = 50 if symbol == "NIFTY" else 100
    return round(spot / gap) * gap


def process_chain(records: list, symbol: str, spot: float = None) -> dict:
    """
    Input : list of strike dicts from fetcher.py
    Output: structured dict for formatter.py
    """
    if not records:
        raise ValueError(f"Empty records for {symbol}")

    gap = 50 if symbol == "NIFTY" else 100

    # Use real live spot price from NSE index token
    if spot is None:
        raise ValueError(f"Spot price missing for {symbol} — cannot determine ATM")

    atm = get_atm(spot, symbol)
    logger.info(f"{symbol} spot={spot} ATM={atm}")

    # ── Major Walls ──────────────────────────────────────────────────────────
    # CE walls: only above ATM (resistance above market)
    # PE walls: only below ATM (support below market)
    ce_candidates = [r for r in records if r["strike"] >= atm]
    pe_candidates = [r for r in records if r["strike"] <= atm]
    ce_walls = sorted(ce_candidates, key=lambda x: x["ce_oi"], reverse=True)[:TOP_WALLS]
    pe_walls = sorted(pe_candidates, key=lambda x: x["pe_oi"], reverse=True)[:TOP_WALLS]

    # ── Battle Zone ──────────────────────────────────────────────────────────
    battle_zone = [r for r in records
                   if abs(r["strike"] - atm) <= STRIKE_WINDOW * gap]

    for s in battle_zone:
        ce = s["ce_oi"] or 1
        pe = s["pe_oi"] or 1
        s["pcr"] = round(pe / ce, 2)
        s["bias"] = (
            "Bullish"  if s["pcr"] >= 1.5 else
            "Neutral"  if s["pcr"] >= 0.8 else
            "Bearish"
        )

    # ── Overall PCR ──────────────────────────────────────────────────────────
    total_ce   = sum(r["ce_oi"] for r in records) or 1
    total_pe   = sum(r["pe_oi"] for r in records)
    overall_pcr = round(total_pe / total_ce, 2)

    bias_label = (
        "Strongly Bullish" if overall_pcr >= 1.5 else
        "Bullish"          if overall_pcr >= 1.2 else
        "Neutral"          if overall_pcr >= 0.8 else
        "Bearish"          if overall_pcr >= 0.5 else
        "Strongly Bearish"
    )

    return {
        "symbol":       symbol,
        "spot":         spot,
        "atm":          atm,
        "ce_walls":     ce_walls,
        "pe_walls":     pe_walls,
        "battle_zone":  battle_zone,
        "overall_pcr":  overall_pcr,
        "overall_bias": bias_label,
    }

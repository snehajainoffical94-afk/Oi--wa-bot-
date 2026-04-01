"""
Formatter — Trader-style OI Flow summary.
Clean, Telegram/WhatsApp-friendly, ~14 lines per instrument.
"""
from datetime import datetime
import pytz

IST = pytz.timezone("Asia/Kolkata")


# ── Number Helpers ─────────────────────────────────────────────────────────────

def _fmt(oi: int) -> str:
    """Format OI in Indian shorthand: 220000 → 2.2L, 1500000 → 15.0L"""
    if oi == 0:
        return "0"
    l = oi / 100_000
    return f"{l/100:.1f}Cr" if l >= 100 else f"{l:.1f}L"


def _signed(chg: int) -> str:
    """Signed OI change: +2.2L / -1.4L"""
    if chg == 0:
        return "0"
    sign = "+" if chg > 0 else "-"
    return f"{sign}{_fmt(abs(chg))}"


# ── Main Builder ───────────────────────────────────────────────────────────────

def format_update(data: dict) -> str:
    sym    = data["symbol"]
    spot   = data["spot"]
    atm    = data["atm"]
    now    = datetime.now(IST).strftime("%I:%M %p")
    label  = "BANK NIFTY" if sym == "BANKNIFTY" else sym

    call_zones  = data.get("call_zones", [])
    put_zones   = data.get("put_zones", [])
    max_chg     = data.get("max_change", {})
    total_ce    = data.get("total_ce_day", 0)
    total_pe    = data.get("total_pe_day", 0)
    cur_pcr     = data.get("current_pcr", 0)
    day_pcr     = data.get("day_change_pcr")
    unwind      = data.get("unwinding", {})
    view        = data.get("view", {})

    lines = [
        f"*{label} — OI FLOW (MONTHLY EXPIRY)*",
        f"{now}  |  Spot: *{spot:,.0f}*",
        "",
    ]

    # ── Call Writing ──────────────────────────────────────────────────────────
    lines.append("*Call Writing*")
    if call_zones:
        for z in call_zones:
            lines.append(f"🔴 {z['strike']:,} → {_signed(z['ce_oi_change'])}")
    else:
        lines.append("No significant call writing")

    lines.append("")

    # ── Put Writing ───────────────────────────────────────────────────────────
    lines.append("*Put Writing*")
    if put_zones:
        for z in put_zones:
            lines.append(f"🟢 {z['strike']:,} → {_signed(z['pe_oi_change'])}")
    else:
        lines.append("No significant put writing")

    lines.append("")

    # ── Max Change Today ──────────────────────────────────────────────────────
    ce_max = max_chg.get("ce")
    pe_max = max_chg.get("pe")
    if ce_max and pe_max:
        lines.append(
            f"*Max Change Today*\n"
            f"CE: {ce_max['strike']:,} → {_signed(ce_max['ce_oi_change'])}  "
            f"|  PE: {pe_max['strike']:,} → {_signed(pe_max['pe_oi_change'])}"
        )
        lines.append("")

    # ── Total OI Change ───────────────────────────────────────────────────────
    lines.append(
        f"*Total OI Change*\n"
        f"CE: {_signed(total_ce)}  |  PE: {_signed(total_pe)}"
    )
    lines.append("")

    # ── PCR ───────────────────────────────────────────────────────────────────
    day_pcr_str = f"{day_pcr}" if day_pcr is not None else "N/A"
    lines.append(
        f"*PCR*\n"
        f"Current: *{cur_pcr}*  |  Day Change: *{day_pcr_str}*"
    )
    lines.append("")

    # ── Unwinding (only if meaningful) ────────────────────────────────────────
    ce_uw = unwind.get("ce")
    pe_uw = unwind.get("pe")
    if ce_uw or pe_uw:
        lines.append("*Unwinding*")
        if ce_uw:
            meaning = "resistance weakening" if ce_uw["strike"] > atm else "OTM CE exit"
            lines.append(f"⚠️ CE: {ce_uw['strike']:,} → {_signed(ce_uw['ce_oi_change'])}  ({meaning})")
        if pe_uw:
            meaning = "support weakening" if pe_uw["strike"] < atm else "OTM PE exit"
            lines.append(f"⚠️ PE: {pe_uw['strike']:,} → {_signed(pe_uw['pe_oi_change'])}  ({meaning})")
        lines.append("")

    # ── View ──────────────────────────────────────────────────────────────────
    sup = view.get("support", 0)
    res = view.get("resistance", 0)
    bias = view.get("bias", "Neutral")
    if "Bullish" in bias:
        bias_icon = "🟢"
    elif "Bearish" in bias:
        bias_icon = "🔴"
    else:
        bias_icon = "⚪"

    lines += [
        "*View*",
        f"🟢 Support *{sup:,}*  |  🔴 Resistance *{res:,}*",
        f"{bias_icon} *{bias}*",
    ]

    return "\n".join(lines)


# ── Spike Alert (unchanged) ────────────────────────────────────────────────────

def format_spike_alert(symbol: str, spot: float, spikes: list) -> str:
    now = datetime.now(IST).strftime("%I:%M %p")
    sym_label = "BANK NIFTY" if symbol == "BANKNIFTY" else symbol
    lines = [
        f"🚨 *SPIKE ALERT — {sym_label}*",
        f"{now}  |  Spot: {spot:,.0f}",
        "",
        "Unusual OI build-up:",
        "",
    ]
    for sp in spikes:
        icon = "🔴" if sp["type"] == "CE" else "🟢"
        lines.append(f"{icon} *{sp['strike']:,} {sp['type']}* — OI +{sp['pct']:.0f}%")
        lines.append(f"   {_fmt(sp['prev_oi'])} → {_fmt(sp['curr_oi'])}")
    lines += ["", "_Review your open positions._"]
    return "\n".join(lines)

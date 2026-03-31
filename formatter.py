from datetime import datetime
import pytz

IST = pytz.timezone("Asia/Kolkata")


def to_lakhs(oi: int) -> str:
    if oi == 0:
        return "0"
    l = oi / 100_000
    return f"{l/100:.1f}Cr" if l >= 100 else f"{l:.1f}L"


def chg_str(chg: int) -> str:
    if chg > 0: return f"▲{to_lakhs(chg)}"
    if chg < 0: return f"▼{to_lakhs(abs(chg))}"
    return "─"


def format_update(data: dict) -> str:
    sym   = data["symbol"]
    spot  = data["spot"]
    atm   = data["atm"]
    pcr   = data["overall_pcr"]
    bias  = data["overall_bias"]
    now   = datetime.now(IST).strftime("%I:%M %p")

    bias_icon = "🟢" if "Bullish" in bias else ("🔴" if "Bearish" in bias else "⚪")
    sym_label = "BANK NIFTY" if sym == "BANKNIFTY" else sym

    lines = [
        f"📊 *{sym_label} — OI SNAPSHOT*",
        f"🕐 {now}  |  Spot: *{spot:,.0f}*  |  ATM: *{atm:,}*",
        "",
        "━━━━ 🧱 MAJOR WALLS ━━━━",
    ]

    # Resistance walls (CE)
    for i, w in enumerate(data["ce_walls"]):
        tag = "MAX RESISTANCE" if i == 0 else f"#{i+1} Resistance"
        lines.append(f"🔴 {tag}: *{w['strike']:,}*  |  OI: {to_lakhs(w['ce_oi'])}  |  Δ {chg_str(w['ce_oi_change'])}")

    lines.append("")

    # Support walls (PE)
    for i, w in enumerate(data["pe_walls"]):
        tag = "MAX SUPPORT" if i == 0 else f"#{i+1} Support"
        lines.append(f"🟢 {tag}: *{w['strike']:,}*  |  OI: {to_lakhs(w['pe_oi'])}  |  Δ {chg_str(w['pe_oi_change'])}")

    lines += ["", "━━━━ ⚡ BATTLE ZONE ━━━━"]

    # Sort: above ATM descending, ATM, below ATM descending
    bz = sorted(data["battle_zone"], key=lambda x: x["strike"], reverse=True)
    for s in bz:
        atm_tag = " ◄ ATM" if s["strike"] == atm else ""
        b_icon  = "🟢" if s.get("bias") == "Bullish" else ("🔴" if s.get("bias") == "Bearish" else "⚪")
        lines.append(
            f"{b_icon} *{s['strike']:,}*{atm_tag}  |  "
            f"CE: {to_lakhs(s['ce_oi'])} ({chg_str(s['ce_oi_change'])})  "
            f"PE: {to_lakhs(s['pe_oi'])} ({chg_str(s['pe_oi_change'])})  "
            f"PCR: {s.get('pcr', 0)}"
        )

    lines += [
        "",
        f"━━━━ 📈 SENTIMENT ━━━━",
        f"{bias_icon} Overall PCR: *{pcr}*  →  {bias}",
        "",
        f"_⏰ Next update in 60 min_",
    ]

    return "\n".join(lines)


def format_spike_alert(symbol: str, spot: float, spikes: list) -> str:
    now = datetime.now(IST).strftime("%I:%M %p")
    sym_label = "BANK NIFTY" if symbol == "BANKNIFTY" else symbol
    lines = [
        f"🚨 *SPIKE ALERT — {sym_label}*",
        f"🕐 {now}  |  Spot: {spot:,.0f}",
        "",
        "⚠️ Unusual OI build-up detected:",
        "",
    ]
    for sp in spikes:
        icon = "🔴" if sp["type"] == "CE" else "🟢"
        lines.append(
            f"{icon} *{sp['strike']:,} {sp['type']}* — OI jumped *+{sp['pct']:.0f}%*"
        )
        lines.append(f"   {to_lakhs(sp['prev_oi'])} → {to_lakhs(sp['curr_oi'])}")
    lines += ["", "_Review your open positions._"]
    return "\n".join(lines)

import json, os
from datetime import date
from config import SPIKE_THRESHOLD

STATE_FILE = "state/oi_state.json"
os.makedirs("state", exist_ok=True)


def _load() -> dict:
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE) as f:
        return json.load(f)


def _save(data: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(data, f)


def save_snapshot(symbol: str, processed: dict):
    state = _load()
    today = str(date.today())
    state.setdefault(today, {})[symbol] = {
        s["strike"]: {"ce_oi": s["ce_oi"], "pe_oi": s["pe_oi"]}
        for s in processed["battle_zone"]
    }
    _save(state)


def detect_spikes(symbol: str, processed: dict) -> list:
    state = _load()
    today = str(date.today())
    prev  = state.get(today, {}).get(symbol, {})
    spikes = []

    for s in processed["battle_zone"]:
        strike = str(s["strike"])
        if strike not in prev:
            continue

        for opt_type in ("ce", "pe"):
            curr_oi = s[f"{opt_type}_oi"]
            prev_oi = prev[strike][f"{opt_type}_oi"]
            if prev_oi <= 0:
                continue
            pct = (curr_oi - prev_oi) / prev_oi * 100
            if pct >= SPIKE_THRESHOLD:
                spikes.append({
                    "strike":   s["strike"],
                    "type":     opt_type.upper(),
                    "prev_oi":  prev_oi,
                    "curr_oi":  curr_oi,
                    "pct":      pct,
                })

    return spikes

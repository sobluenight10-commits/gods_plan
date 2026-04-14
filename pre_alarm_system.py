"""
OLYMPUS full-auto pre-alarm system — liquidity expectation corridor, velocity,
surprise score vs rolling band, macro_liquidity_regime for GEM, Telegram alerts.

FRED prints are slow-moving; we alert on corridor breaks and abnormal velocity,
not on noise. History: data/liquidity_history.json — state: data/pre_alarm_state.json
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("titan_k.pre_alarm")

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
HISTORY_PATH = os.path.join(DATA_DIR, "liquidity_history.json")
ALARM_STATE_PATH = os.path.join(DATA_DIR, "pre_alarm_state.json")
DIRECTIVES_PATH = os.path.join(DATA_DIR, "directives.json")

try:
    from config import (
        LIQUIDITY_ROLLING_DAYS,
        PRE_ALARM_SURPRISE_ALERT,
        PRE_ALARM_VELOCITY_ALERT_B,
        PRE_ALARM_CORRIDOR_MARGIN_B,
        LIQUIDITY_BOOTSTRAP_LOW_B,
        LIQUIDITY_BOOTSTRAP_HIGH_B,
    )
except Exception:
    LIQUIDITY_ROLLING_DAYS = 90
    PRE_ALARM_SURPRISE_ALERT = 0.82
    PRE_ALARM_VELOCITY_ALERT_B = 85.0
    PRE_ALARM_CORRIDOR_MARGIN_B = 15.0
    LIQUIDITY_BOOTSTRAP_LOW_B = 2100.0
    LIQUIDITY_BOOTSTRAP_HIGH_B = 2900.0


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load_json(path: str, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _percentile(sorted_vals: List[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    k = (n - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, n - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (k - f) * (sorted_vals[c] - sorted_vals[f])


def _append_history(net_liq: float, reserves: float, tga: float, rrp: float) -> List[Dict]:
    raw = _load_json(HISTORY_PATH, {"snapshots": []})
    snaps: List[Dict] = raw.get("snapshots") or []
    day = _today_utc()
    row = {
        "date": day,
        "net_liq": round(float(net_liq), 1),
        "reserves_b": round(float(reserves), 1),
        "tga_b": round(float(tga), 1),
        "rrp_b": round(float(rrp), 1),
        "ts_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    # Replace same calendar day (latest wins)
    snaps = [s for s in snaps if s.get("date") != day]
    snaps.append(row)
    snaps.sort(key=lambda x: x.get("date") or "")
    max_keep = 550
    if len(snaps) > max_keep:
        snaps = snaps[-max_keep:]
    _save_json(HISTORY_PATH, {"snapshots": snaps})
    return snaps


def _velocity_b(snaps: List[Dict], days: int) -> Optional[float]:
    if not snaps:
        return None
    now = snaps[-1].get("net_liq")
    if now is None:
        return None
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    past = [s for s in snaps if (s.get("date") or "") <= cutoff]
    if not past:
        # oldest available
        past = [snaps[0]]
    old = past[-1].get("net_liq")
    if old is None:
        return None
    return float(now) - float(old)


def _compute_corridor(snaps: List[Dict]) -> Tuple[float, float, float, str]:
    """Returns low, mid, high, source note."""
    cutoff_d = (datetime.now(timezone.utc) - timedelta(days=LIQUIDITY_ROLLING_DAYS)).strftime("%Y-%m-%d")
    recent = [s for s in snaps if (s.get("date") or "") >= cutoff_d and s.get("net_liq") is not None]
    src = recent if len(recent) >= 3 else [s for s in snaps if s.get("net_liq") is not None]
    vals = [float(s["net_liq"]) for s in src]
    if len(vals) < 5:
        lo, hi = LIQUIDITY_BOOTSTRAP_LOW_B, LIQUIDITY_BOOTSTRAP_HIGH_B
        mid = (lo + hi) / 2.0
        return lo, mid, hi, f"bootstrap band (need {5 - len(vals)} more FRED points for auto p25–p75)"
    sv = sorted(vals)
    lo = _percentile(sv, 25)
    hi = _percentile(sv, 75)
    mid = (lo + hi) / 2.0
    return lo, mid, hi, f"p25–p75 over last ~{LIQUIDITY_ROLLING_DAYS}d window ({len(vals)} samples)"


def _surprise(net: float, mid: float, lo: float, hi: float) -> float:
    half = max((hi - lo) / 2.0, 50.0)
    return (net - mid) / half


def _macro_regime(net: float, lo: float, hi: float, vel4w: Optional[float]) -> str:
    # Must match minerva_gem.LIQ_MULT keys: tight / neutral / loose
    if net < lo - PRE_ALARM_CORRIDOR_MARGIN_B:
        return "tight"
    if net > hi + PRE_ALARM_CORRIDOR_MARGIN_B:
        return "loose"
    if vel4w is not None and vel4w < -PRE_ALARM_VELOCITY_ALERT_B * 0.5:
        return "tight"
    if vel4w is not None and vel4w > PRE_ALARM_VELOCITY_ALERT_B * 0.5:
        return "loose"
    return "neutral"


def _alarm_key_hash(kind: str, detail: str) -> str:
    h = hashlib.sha256(f"{kind}|{detail}".encode()).hexdigest()[:16]
    return f"{kind}_{h}"


def _should_fire(state: Dict, key: str, cooldown_hours: float = 20.0) -> bool:
    last = state.get("last_fires", {}).get(key)
    if not last:
        return True
    try:
        t = datetime.fromisoformat(last.replace("Z", "+00:00"))
        if datetime.now(timezone.utc) - t < timedelta(hours=cooldown_hours):
            return False
    except Exception:
        return True
    return True


def _record_fire(state: Dict, key: str) -> None:
    cur = _load_json(ALARM_STATE_PATH, {"last_fires": {}})
    cur.setdefault("last_fires", {})[key] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    state.setdefault("last_fires", {})[key] = cur["last_fires"][key]
    _save_json(ALARM_STATE_PATH, cur)


def _send_pre_alarm_tg(html: str) -> None:
    try:
        from telegram_bot import send_telegram

        send_telegram(html)
    except Exception as e:
        logger.error("pre_alarm telegram: %s", e)


def enrich_liquidity_directives_and_alarm(fred_out: Dict[str, Any]) -> None:
    """
    Call after FRED fetch + write_liquidity_to_directives.
    fred_out: dict with net_liq, reserves in billions context optional.
    """
    net = fred_out.get("net_liq")
    if net is None:
        return
    # battle_rhythm passes res_b tga rrp from caller — may be in fred_out under different keys
    res = fred_out.get("res_b") or fred_out.get("reserves_b")
    tga = fred_out.get("tga_b")
    rrp = fred_out.get("rrp_b")
    if res is None or tga is None or rrp is None:
        # derive from raw millions if present
        _m = 1000.0
        if fred_out.get("reserves") is not None:
            res = float(fred_out["reserves"]) / _m
            tga = float(fred_out["tga"]) / _m
            rrp = float(fred_out["rrp"]) / _m

    if res is None or tga is None or rrp is None:
        logger.warning("pre_alarm: missing components, skip enrich")
        return

    snaps = _append_history(float(net), float(res), float(tga), float(rrp))
    lo, mid, hi, band_note = _compute_corridor(snaps)
    v7 = _velocity_b(snaps, 7)
    v28 = _velocity_b(snaps, 28)
    surprise = _surprise(float(net), mid, lo, hi)
    margin = PRE_ALARM_CORRIDOR_MARGIN_B
    if float(net) < lo - margin:
        corridor = "BELOW"
    elif float(net) > hi + margin:
        corridor = "ABOVE"
    else:
        corridor = "INSIDE"

    regime = _macro_regime(float(net), lo, hi, v28)

    d = _load_json(DIRECTIVES_PATH, {})
    liq = d.get("liquidity") or {}
    if fred_out.get("net_liq_text"):
        liq["net_liq_text"] = fred_out["net_liq_text"]
    if fred_out.get("hist_parallel"):
        liq["hist_parallel"] = fred_out["hist_parallel"]
    liq["net_liq_value"] = round(float(net))
    liq["net_liq_b"] = round(float(net))
    liq["macro_liquidity_regime"] = regime
    liq["expectation_low_b"] = round(lo, 1)
    liq["expectation_mid_b"] = round(mid, 1)
    liq["expectation_high_b"] = round(hi, 1)
    liq["expectation_note"] = band_note
    liq["velocity_7d_b"] = None if v7 is None else round(v7, 1)
    liq["velocity_4w_b"] = None if v28 is None else round(v28, 1)
    liq["surprise_score"] = round(surprise, 3)
    liq["corridor_status"] = corridor
    liq["pre_alarm_engine"] = "v1"
    chg = fred_out.get("change")
    if chg is not None:
        sig = "+" if float(chg) >= 0 else "-"
        if v28 is not None:
            vs = "+" if v28 >= 0 else ""
            liq["change_text"] = (
                f"vs prior FRED print: {sig}${abs(float(chg)):.0f}B · 4w vel {vs}{v28:.0f}B"
            )
        else:
            liq["change_text"] = f"vs prior FRED print: {sig}${abs(float(chg)):.0f}B"
    else:
        if v28 is not None:
            liq["change_text"] = (
                f"4w velocity: {v28:+.0f}B vs band ${lo:.0f}B–${hi:.0f}B"
            )
        else:
            liq["change_text"] = "—"
    d["liquidity"] = liq
    d["pre_alarm"] = {
        "last_run_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "liquidity_corridor": corridor,
        "surprise": round(surprise, 3),
    }
    si = d.get("system_intel") or {}
    si["pre_alarm_engine"] = "v1"
    si["liquidity_intel_updated_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    d["system_intel"] = si
    _save_json(DIRECTIVES_PATH, d)

    # --- Telegram pre-alarms (deduped) ---
    st = _load_json(ALARM_STATE_PATH, {"last_fires": {}})

    if corridor != "INSIDE" and _should_fire(st, f"corridor_{corridor}", 18.0):
        _send_pre_alarm_tg(
            "🚨 <b>OLYMPUS PRE-ALARM · LIQUIDITY CORRIDOR</b>\n"
            f"Net <b>${float(net):.0f}B</b> is <b>{corridor}</b> the "
            f"p25–p75 band (${lo:.0f}B – ${hi:.0f}B).\n"
            f"Surprise score: <b>{surprise:+.2f}</b> · regime → <b>{regime}</b>\n"
            f"<i>{band_note}</i>"
        )
        _record_fire(st, f"corridor_{corridor}")

    if v28 is not None and abs(v28) >= PRE_ALARM_VELOCITY_ALERT_B and _should_fire(st, "velocity_4w", 18.0):
        _send_pre_alarm_tg(
            "⚡ <b>OLYMPUS PRE-ALARM · 4W VELOCITY</b>\n"
            f"Net liq 4w change <b>{v28:+.0f}B</b> (threshold ±{PRE_ALARM_VELOCITY_ALERT_B:.0f}B).\n"
            f"Current net <b>${float(net):.0f}B</b> · regime <b>{regime}</b>"
        )
        _record_fire(st, "velocity_4w")

    if abs(surprise) >= PRE_ALARM_SURPRISE_ALERT and corridor == "INSIDE" and _should_fire(st, "surprise", 20.0):
        _send_pre_alarm_tg(
            "📊 <b>OLYMPUS PRE-ALARM · SURPRISE VS MID</b>\n"
            f"Inside band by label but vs mid: <b>{surprise:+.2f}</b> "
            f"(alert ≥ {PRE_ALARM_SURPRISE_ALERT}).\n"
            f"Net ${float(net):.0f}B · mid ${mid:.0f}B"
        )
        _record_fire(st, "surprise")


def run_scheduled_fred_refresh() -> None:
    """Hourly: pull FRED + enrich + alarms (safe if FRED unchanged)."""
    try:
        from battle_rhythm import fetch_fred_liquidity

        fetch_fred_liquidity()
        logger.info("scheduled FRED refresh done")
    except Exception as e:
        logger.warning("scheduled FRED refresh: %s", e)

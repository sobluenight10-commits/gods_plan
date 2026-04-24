"""
BEHAVIORAL CIRCUIT BREAKERS — OLYMPUS-SENTINEL Layer 8.

The system does not execute trades. GOD does. Every OLYMPUS lesson so
far (AVAV, KTOS premium trap, TMO thesis drift, GEVO thesis rot) was
a HUMAN decision the system could have vetoed but the human overrode.

This module adds three mechanical gates that activate between the
moment a signal becomes visible and the moment an order is placed:

  1. check_cooldown(ticker, order_eur, day_move_pct):
       Forces a 5-minute cooldown on any new order > €500 when the
       underlying moved > 5% that day. The cooldown entry lives in
       data/cooldowns.json until it expires.

  2. require_thesis_restatement(ticker, action):
       Before any CORE trim or EXIT-that-is-not-thesis-dead, force a
       one-sentence thesis restatement typed into
       data/decisions_pending.json. If the field is empty, the action
       is blocked.

  3. log_override(ticker, system_verb, user_verb, reason, trade_id):
       Records every instance where the human contradicts the system.
       Stored in data/overrides.json for pattern learning:
       "GOD always sells winners too early" / "GOD refuses to EXIT when
       OPS ≥ 200" — patterns that make the system self-aware.

All three feed `data/behavioral_state.json` for the dashboard so the
active cooldowns, pending restatements, and override history are visible.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

DATA = os.path.join(BASE, "data")
COOLDOWNS = os.path.join(DATA, "cooldowns.json")
PENDING = os.path.join(DATA, "decisions_pending.json")
OVERRIDES = os.path.join(DATA, "overrides.json")
STATE_OUT = os.path.join(DATA, "behavioral_state.json")
WEBROOT_OUT = "/var/www/html/behavioral_state.json"

# Thresholds (tune in one place)
COOLDOWN_TRIGGER_ORDER_EUR = 500.0
COOLDOWN_TRIGGER_MOVE_PCT = 5.0         # absolute intraday move that arms the gate
COOLDOWN_SECONDS = 5 * 60               # 5 minutes — forces you past the adrenaline window
CORE_TICKERS_FILE = os.path.join(BASE, "gem_inputs", "core_satellite.json")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _load(path: str, default: Any) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _core_tickers() -> List[str]:
    cs = _load(CORE_TICKERS_FILE, {"core_tickers": []})
    return cs.get("core_tickers") or []


# ---------------------------------------------------------------------------
# 1. Cooldown gate
# ---------------------------------------------------------------------------

def check_cooldown(
    ticker: str,
    order_eur: float,
    day_move_pct: float,
    side: str = "BUY",
) -> Dict[str, Any]:
    """
    Return {"allow": bool, "seconds_remaining": int, "reason": str,
            "arm_if_violated": bool}.

    If the order is large AND the day move is large AND no cooldown is
    currently active for this ticker, arm one and refuse for 5 minutes.
    If a cooldown is already active and has not expired, refuse with
    seconds_remaining. Otherwise, allow.
    """
    cool = _load(COOLDOWNS, {"entries": {}})
    entries: Dict[str, Any] = cool.get("entries") or {}
    now = _now_utc()

    existing = entries.get(ticker)
    if existing:
        try:
            expires = datetime.fromisoformat(existing["expires_utc"].replace("Z", "+00:00"))
        except Exception:
            expires = now
        remaining = int((expires - now).total_seconds())
        if remaining > 0:
            return {
                "allow": False,
                "seconds_remaining": remaining,
                "reason": f"cooldown active until {existing['expires_utc']} — "
                          f"{existing.get('reason', 'behavioral gate')}",
                "armed": False,
            }
        else:
            # expired — remove and continue
            entries.pop(ticker, None)

    arm = (
        abs(order_eur) >= COOLDOWN_TRIGGER_ORDER_EUR
        and abs(day_move_pct) >= COOLDOWN_TRIGGER_MOVE_PCT
    )
    if arm:
        expires = now + timedelta(seconds=COOLDOWN_SECONDS)
        entries[ticker] = {
            "armed_utc": _iso(now),
            "expires_utc": _iso(expires),
            "reason": f"{side} €{order_eur:.0f} while {ticker} moved {day_move_pct:+.1f}% today",
            "side": side,
            "order_eur": order_eur,
            "day_move_pct": day_move_pct,
        }
        cool["entries"] = entries
        _save(COOLDOWNS, cool)
        return {
            "allow": False,
            "seconds_remaining": COOLDOWN_SECONDS,
            "reason": (
                f"Cooldown armed: {COOLDOWN_SECONDS//60} min. "
                f"{ticker} moved {day_move_pct:+.1f}% today, order €{order_eur:.0f} ≥ "
                f"€{COOLDOWN_TRIGGER_ORDER_EUR:.0f}. Re-issue after the timer."
            ),
            "armed": True,
        }

    return {
        "allow": True,
        "seconds_remaining": 0,
        "reason": "below behavioral trigger (order < €500 or move < 5%)",
        "armed": False,
    }


def pending_cooldowns() -> List[Dict[str, Any]]:
    """Return only still-active cooldowns (expired ones are auto-pruned)."""
    cool = _load(COOLDOWNS, {"entries": {}})
    now = _now_utc()
    out = []
    to_drop = []
    for tk, entry in (cool.get("entries") or {}).items():
        try:
            expires = datetime.fromisoformat(entry["expires_utc"].replace("Z", "+00:00"))
        except Exception:
            to_drop.append(tk); continue
        remaining = int((expires - now).total_seconds())
        if remaining <= 0:
            to_drop.append(tk); continue
        out.append({
            "ticker": tk,
            "expires_utc": entry["expires_utc"],
            "seconds_remaining": remaining,
            "reason": entry.get("reason"),
            "side": entry.get("side"),
            "order_eur": entry.get("order_eur"),
            "day_move_pct": entry.get("day_move_pct"),
        })
    if to_drop:
        for tk in to_drop:
            (cool.get("entries") or {}).pop(tk, None)
        _save(COOLDOWNS, cool)
    return out


# ---------------------------------------------------------------------------
# 2. Thesis-restatement gate (for CORE trims / non-dead exits)
# ---------------------------------------------------------------------------

def _needs_restatement(ticker: str, action: str) -> bool:
    action = (action or "").upper()
    if ticker in _core_tickers() and action in ("TRIM", "EXIT"):
        return True
    # Any EXIT of a non-thesis-dead position needs restatement
    if action == "EXIT":
        return True
    return False


def require_thesis_restatement(
    ticker: str,
    action: str,
    thesis_sentence: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Gate any CORE trim/exit behind a typed thesis restatement.

    If thesis_sentence is provided AND non-trivial, record the decision
    and return {"allow": True}. Otherwise append a pending-decision entry
    and return {"allow": False, "reason": ...}.
    """
    if not _needs_restatement(ticker, action):
        return {"allow": True, "reason": "action does not require restatement", "pending_id": None}

    pending = _load(PENDING, {"entries": []})
    entries: List[Dict[str, Any]] = pending.get("entries") or []

    if not thesis_sentence or len(thesis_sentence.strip()) < 20:
        # Block — create / update a pending entry
        pending_id = f"{ticker}_{action}_{_iso(_now_utc())[:19]}"
        already = any(e.get("id") == pending_id for e in entries)
        if not already:
            entries.append({
                "id": pending_id,
                "ticker": ticker,
                "action": action.upper(),
                "opened_utc": _iso(_now_utc()),
                "status": "PENDING_RESTATEMENT",
                "prompt": (
                    f"Before you {action.upper()} {ticker}, type one sentence explaining why "
                    f"the thesis has changed. Minimum 20 chars."
                ),
                "sentence": thesis_sentence or "",
            })
            pending["entries"] = entries
            _save(PENDING, pending)
        return {
            "allow": False,
            "reason": f"Thesis restatement required before {action.upper()} on {ticker}.",
            "pending_id": pending_id,
        }

    # Allowed — close out any pending entry and log the accepted statement
    for e in entries:
        if e.get("ticker") == ticker and e.get("action") == action.upper() and e.get("status") == "PENDING_RESTATEMENT":
            e["status"] = "RESOLVED"
            e["sentence"] = thesis_sentence.strip()
            e["resolved_utc"] = _iso(_now_utc())
    pending["entries"] = entries
    _save(PENDING, pending)
    return {"allow": True, "reason": "thesis restated", "pending_id": None}


def pending_thesis_restatements() -> List[Dict[str, Any]]:
    pending = _load(PENDING, {"entries": []})
    return [e for e in (pending.get("entries") or []) if e.get("status") == "PENDING_RESTATEMENT"]


# ---------------------------------------------------------------------------
# 3. Override logger (pattern learning)
# ---------------------------------------------------------------------------

def log_override(
    ticker: str,
    system_verb: str,
    user_verb: str,
    reason: str,
    *,
    trade_id: Optional[str] = None,
    user_thesis: Optional[str] = None,
    system_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Append an override event. Later reconciliation (when trade closes)
    will set outcome → pattern file picks it up."""
    data = _load(OVERRIDES, {"entries": []})
    entries: List[Dict[str, Any]] = data.get("entries") or []
    eid = trade_id or f"{ticker}_{_iso(_now_utc())[:19]}"
    entry = {
        "id": eid,
        "ticker": ticker,
        "system_verb": (system_verb or "").upper(),
        "user_verb": (user_verb or "").upper(),
        "delta_kind": _classify_override(system_verb, user_verb),
        "recorded_utc": _iso(_now_utc()),
        "reason": reason,
        "user_thesis": user_thesis,
        "system_context": system_context or {},
        "resolved_pnl_pct": None,
        "who_was_right": None,  # filled in when lesson card is written
    }
    entries.append(entry)
    data["entries"] = entries
    _save(OVERRIDES, data)
    return entry


def _classify_override(system_verb: str, user_verb: str) -> str:
    s = (system_verb or "").upper()
    u = (user_verb or "").upper()
    if s == u:
        return "agreement"
    if s in ("WATCH", "HOLD") and u in ("BUY", "ADD"):
        return "overconfidence_buy"
    if s in ("BUY", "ADD") and u in ("WATCH", "HOLD"):
        return "conservative_miss"
    if s == "HOLD" and u in ("TRIM", "EXIT"):
        return "premature_harvest"
    if s in ("TRIM", "EXIT") and u == "HOLD":
        return "hope_hold_trap"
    return "other"


# ---------------------------------------------------------------------------
# Publish behavioral_state.json for dashboard
# ---------------------------------------------------------------------------

def publish_state() -> Dict[str, Any]:
    cds = pending_cooldowns()
    pr = pending_thesis_restatements()
    overrides = _load(OVERRIDES, {"entries": []}).get("entries") or []

    # Compact override patterns: last 25 + kind histogram
    recent = overrides[-25:]
    kinds: Dict[str, int] = {}
    for e in overrides:
        k = e.get("delta_kind") or "other"
        kinds[k] = kinds.get(k, 0) + 1

    state = {
        "schema_version": 1,
        "generated_utc": _iso(_now_utc()),
        "active_cooldowns": cds,
        "pending_restatements": pr,
        "override_history_total": len(overrides),
        "override_kinds": kinds,
        "override_recent": recent,
        "thresholds": {
            "cooldown_trigger_order_eur": COOLDOWN_TRIGGER_ORDER_EUR,
            "cooldown_trigger_move_pct": COOLDOWN_TRIGGER_MOVE_PCT,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "core_tickers_require_restatement": _core_tickers(),
        },
    }
    _save(STATE_OUT, state)
    try:
        import shutil
        shutil.copy2(STATE_OUT, WEBROOT_OUT)
    except Exception:
        pass
    return state


if __name__ == "__main__":
    out = publish_state()
    print(json.dumps(out, indent=2))

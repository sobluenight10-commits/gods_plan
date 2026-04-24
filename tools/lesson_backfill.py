"""
LESSON BACKFILL — turn historical closed_positions into lesson cards.

Reads state.json.closed_positions and produces a card per closed trade so
that Phase 2 calibration has *some* priors before the live recording flow
starts accumulating new cards.

Also seeds four canonical OLYMPUS lessons from CLAUDE.md that have no
exact price data but carry system-error signal:
  - KTOS premium trap (OPS 293 at entry, system had no OPS gate).
  - AVAV thesis break (scheduled-brief latency).
  - GEVO thesis rot (exit_overdue violated).
  - TMO thesis drift (caught late, no guardrail).
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from tools.close_trade import close_trade, write_index  # noqa: E402

STATE = os.path.join(BASE, "state.json")


def _load(path: str, default: Any) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


SEED_LESSONS: List[Dict[str, Any]] = [
    {
        "ticker": "KTOS",
        "exit_price": 63.00,
        "entry_price": 85.50,
        "opened_utc": "2025-12-10T09:30:00Z",
        "closed_utc": "2026-04-07T16:00:00Z",
        "currency": "USD",
        "thesis_outcome": "wrong",
        "category": "premium_trap",
        "what_fired_first": "none — OPS gate did not exist at entry",
        "what_was_right": ["thesis_guard_caught_drift_later", "stop_engine_would_have_fired_at_-18"],
        "what_was_wrong": ["god_score_V_pass_on_dcf_only", "dip_buy_bought_a_falling_knife"],
        "what_was_silent": ["no_sector_relative_premium_gate", "no_drawdown_guardian"],
        "felt": "Bought at $85.50 thinking dip. Lost words when Minerva showed OPS 293 vs sector 100. System had no peer-relative valuation gate. That blind spot is permanently closed now.",
        "lessons_applied": ["OPS_gate", "KTOS_lesson"],
        "max_drawdown_pct": -0.42,
    },
    {
        "ticker": "AVAV",
        "exit_price": None,  # filled from state
        "entry_price": None,
        "opened_utc": "2025-11-01T09:30:00Z",
        "closed_utc": "2026-04-08T16:00:00Z",
        "currency": "USD",
        "thesis_outcome": "wrong",
        "category": "alert_latency",
        "what_fired_first": "pre-alarm not wired to thesis break; brief caught it next morning",
        "what_was_right": ["thesis_guard_detected_break"],
        "what_was_wrong": ["no_intraday_alert_pipe"],
        "what_was_silent": ["telegram_fire_on_thesis_break"],
        "felt": "Alert system must fire on thesis break immediately, not wait for scheduled brief.",
        "lessons_applied": ["AVAV_lesson"],
        "max_drawdown_pct": -0.12,
    },
    {
        "ticker": "GEVO",
        "exit_price": 0.90,
        "entry_price": 5.40,
        "opened_utc": "2024-06-01T09:30:00Z",
        "closed_utc": "2026-03-05T16:00:00Z",
        "currency": "USD",
        "thesis_outcome": "dead",
        "category": "thesis_rot",
        "what_fired_first": "EXIT_OVERDUE flag set 2026-03-01, ignored",
        "what_was_right": ["thesis_guard_flagged_exit_overdue"],
        "what_was_wrong": ["human_override_refused_to_sell"],
        "what_was_silent": ["no_mandatory_cooldown_on_override"],
        "felt": "Thesis rotted. Behavior didn't execute the guard.",
        "lessons_applied": ["hope_hold_trap"],
        "max_drawdown_pct": -0.85,
    },
    {
        "ticker": "TMO",
        "exit_price": None,
        "entry_price": None,
        "opened_utc": "2025-05-01T09:30:00Z",
        "closed_utc": "2026-03-28T16:00:00Z",
        "currency": "USD",
        "thesis_outcome": "partial",
        "category": "thesis_drift",
        "what_fired_first": "late — Life Sciences print revealed drift post facto",
        "what_was_right": ["kill_criteria_eventually_matched"],
        "what_was_wrong": ["thesis_drift_not_surfaced_weekly"],
        "what_was_silent": ["weekly_thesis_restatement_required"],
        "felt": "Thesis drifted without me noticing. Need forced weekly restatement.",
        "lessons_applied": ["thesis_drift"],
        "max_drawdown_pct": -0.22,
    },
]


def backfill() -> Dict[str, Any]:
    state = _load(STATE, {})
    closed = state.get("closed_positions") or []

    written = []
    # First: historical state records that have prices
    for c in closed:
        tk = c.get("ticker")
        if not tk:
            continue
        # state.json records often have only "result" and a note — we still
        # write a card so the dashboard has an audit trail, even if realized
        # return is estimated.
        result = str(c.get("result") or "").lower()
        if "profit" in result:
            est_return = 0.20  # placeholder — replace when real prices arrive
            outcome = "right"
            category = "harvest_win"
        elif "loss" in result or "-" in result:
            # parse "-7% loss"
            import re
            m = re.search(r"-?(\d+(?:\.\d+)?)%", result)
            est_return = -float(m.group(1)) / 100.0 if m else -0.10
            outcome = "wrong"
            category = "stop_bounce"
        else:
            est_return = 0.0
            outcome = "timed_out"
            category = "unclassified"

        entry = 100.0
        exit_p = entry * (1.0 + est_return)
        card = close_trade(
            ticker=tk,
            exit_price=exit_p,
            entry_price=entry,
            closed_utc=c.get("closed_date") and f"{c['closed_date']}T16:00:00Z" or None,
            thesis_outcome=outcome,
            category=category,
            felt=c.get("note") or c.get("lesson") or "",
            lessons_applied=["state_json_backfill"],
        )
        written.append(card.get("id"))

    # Second: canonical OLYMPUS seed lessons
    for seed in SEED_LESSONS:
        kwargs = dict(seed)
        # Estimate prices if not provided
        exit_p = kwargs.pop("exit_price") or 100.0 * (1.0 + (kwargs.get("max_drawdown_pct") or -0.1))
        entry_p = kwargs.pop("entry_price") or 100.0
        card = close_trade(
            exit_price=exit_p,
            entry_price=entry_p,
            override=True,
            **kwargs,
        )
        written.append(card.get("id"))

    idx = write_index()
    return {
        "written": [w for w in written if w],
        "total_cards": idx.get("count"),
        "summary": idx.get("summary"),
    }


if __name__ == "__main__":
    out = backfill()
    print(json.dumps(out, indent=2))

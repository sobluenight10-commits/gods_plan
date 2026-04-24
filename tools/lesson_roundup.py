"""
LESSON ROUNDUP — weekly "system-error" digest.

Reads every lesson card and produces `data/lesson_digest.json`:
  - Win/loss/breakeven counts + aggregate P&L.
  - Error pattern distribution (premium_trap, thesis_rot, etc.).
  - Signal-accuracy scoreboard — which signals fired right, wrong, silent.
  - Top-3 actionable patterns for the coming week.

The dashboard and Telegram brief can consume this single file instead of
re-aggregating on the fly.
"""
from __future__ import annotations

import glob
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

LESSONS_DIR = os.path.join(BASE, "data", "lessons")
OUT = os.path.join(BASE, "data", "lesson_digest.json")
WEBROOT = "/var/www/html/lesson_digest.json"


def _load(path: str, default: Any) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def run() -> Dict[str, Any]:
    cards: List[Dict[str, Any]] = []
    for p in sorted(glob.glob(os.path.join(LESSONS_DIR, "*.json"))):
        c = _load(p, None)
        if c:
            cards.append(c)

    n = len(cards)
    wins = losses = breakeven = 0
    pnl_sum = 0.0
    holding_days = []
    cat = Counter()
    outcomes = Counter()
    fired_first = Counter()
    right = Counter()
    wrong = Counter()
    silent = Counter()
    group_pnl = defaultdict(list)

    for c in cards:
        rr = c.get("realized_return") or 0.0
        pnl_sum += rr
        if rr > 0.01:
            wins += 1
        elif rr < -0.01:
            losses += 1
        else:
            breakeven += 1
        holding_days.append(c.get("holding_days") or 0)
        cat[c.get("category") or "unclassified"] += 1
        outcomes[c.get("thesis_outcome") or "timed_out"] += 1
        ff = (c.get("what_fired_first") or "").strip()
        if ff:
            fired_first[ff] += 1
        for sig in c.get("what_was_right") or []:
            right[sig] += 1
        for sig in c.get("what_was_wrong") or []:
            wrong[sig] += 1
        for sig in c.get("what_was_silent") or []:
            silent[sig] += 1
        group_pnl[c.get("group") or "UNCLASSIFIED"].append(rr)

    def _topn(counter: Counter, n: int = 5) -> List[Dict[str, Any]]:
        return [{"key": k, "count": v} for k, v in counter.most_common(n)]

    group_stats = {
        g: {
            "n": len(rs),
            "avg_return_pct": round(sum(rs) / max(1, len(rs)) * 100.0, 2),
            "win_rate_pct": round(sum(1 for r in rs if r > 0) / max(1, len(rs)) * 100.0, 2),
        }
        for g, rs in group_pnl.items()
    }

    # Actionable patterns — single-shot tips for the coming week
    patterns: List[str] = []
    if wrong.get("god_score_V_pass_on_dcf_only", 0) >= 1:
        patterns.append("OPS gate now active — GOD_Score V is DCF-only, not peer-relative.")
    if silent.get("no_mandatory_cooldown_on_override", 0) >= 1:
        patterns.append("Mandatory cooldown gate is online — no large order inside -5% days without 5-min delay.")
    if cat.get("premium_trap", 0) >= 1:
        patterns.append("Any BUY with OPS ≥ 180 is auto-downgraded to WATCH (KTOS will not repeat).")
    if cat.get("thesis_rot", 0) >= 1:
        patterns.append("Thesis-guard auto-flags EXIT_OVERDUE — treat those as binding, not advisory.")

    digest = {
        "schema_version": 1,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "n_cards": n,
        "win_loss": {
            "wins": wins, "losses": losses, "breakeven": breakeven,
            "win_rate_pct": round(wins / max(1, wins + losses) * 100.0, 2),
            "avg_return_pct": round(pnl_sum / max(1, n) * 100.0, 2),
            "median_hold_days": sorted(holding_days)[len(holding_days)//2] if holding_days else 0,
        },
        "by_group": group_stats,
        "by_category": dict(cat),
        "by_outcome": dict(outcomes),
        "signals_right": _topn(right),
        "signals_wrong": _topn(wrong),
        "signals_silent": _topn(silent),
        "first_warning_signals": _topn(fired_first),
        "actionable_patterns": patterns,
        "calibration_status": (
            "ACTIVE" if n >= 20 else f"COLLECTING ({n}/20 needed for CRPS re-weighting)"
        ),
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(digest, f, indent=2, ensure_ascii=False)

    try:
        import shutil
        shutil.copy2(OUT, WEBROOT)
    except Exception:
        pass

    return digest


if __name__ == "__main__":
    out = run()
    print(json.dumps(out, indent=2))

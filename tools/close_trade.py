"""
CLOSE-TRADE LESSON RECORDER — OLYMPUS-SENTINEL Layer 6 (Reflection).

Every time a position is closed (win, loss, thesis-death exit, stop hit,
tactical harvest), this module creates a structured *lesson card* at
`data/lessons/<id>.json`. Those cards are:

  1. The training data that `reflection/post_mortem.py` uses to
     re-weight the forecaster ensemble via CRPS.
  2. The override-learning corpus for behavioral circuit breakers.
  3. The raw material for weekly "system-error" digests.

Without cards, Phase 2 calibration stays permanently frozen on priors.
That is the single biggest reason retail ensembles never mature.

Usage (CLI):
    python tools/close_trade.py --ticker KTOS --exit 63.00 \
        --thesis-outcome dead --category premium_trap \
        --felt "Lost words — OPS was 293 at entry, system never flagged."

Usage (importable):
    from tools.close_trade import close_trade
    close_trade(ticker="KTOS", exit_price=63.00, ...)

Schema (v1):
  id                       "<TICKER>_<YYYY-MM-DD>"
  ticker                   "KTOS"
  opened_utc               "2025-10-14T09:30:00Z"
  closed_utc               "2026-04-07T15:55:00Z"
  holding_days             int
  entry_price, exit_price  float
  currency                 "USD"/"EUR"/...
  realized_return          float  (exit / entry - 1)
  realized_return_1y       float  (annualised; feeds CRPS)
  group                    "CORE"/"SATELLITE"/"UNCLASSIFIED"
  signals_at_entry         snapshot of GEM/OPS/liquidity/vector/thesis
  signals_at_exit          snapshot at close
  forecasts                stored p05/p25/p50/p75/p95 per model at entry
  thesis_outcome           "right"/"wrong"/"partial"/"dead"/"timed_out"
  what_fired_first         first system signal that warned of the outcome
  what_was_right           list of signals that were correct
  what_was_wrong           list of signals that misled
  what_was_silent          list of signals that should have fired but didn't
  category                 "premium_trap"/"stop_bounce"/"thesis_rot"/...
  felt                     freeform human reflection (behavioral gold)
  lessons_applied          which lesson_NN from CLAUDE.md
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

LESSONS_DIR = os.path.join(BASE, "data", "lessons")
PORTFOLIO = os.path.join(BASE, "gem_inputs", "portfolio_all.json")
CORE_SAT = os.path.join(BASE, "gem_inputs", "core_satellite.json")
STATE = os.path.join(BASE, "state.json")
ACTIVE = os.path.join(BASE, "data", "active_actions.json")
FORECASTS = os.path.join(BASE, "data", "forecasts.json")
DIRECTIVES = os.path.join(BASE, "data", "directives.json")
PREMIUM = os.path.join(BASE, "data", "premium_scores.json")
THESIS_HIST = os.path.join(BASE, "data", "thesis_history.json")
WEBROOT_LESSONS_INDEX = "/var/www/html/lessons_index.json"


def _load(path: str, default: Any) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _group_for(ticker: str) -> str:
    cs = _load(CORE_SAT, {"core_tickers": [], "satellite_tickers": []})
    if ticker in (cs.get("core_tickers") or []):
        return "CORE"
    if ticker in (cs.get("satellite_tickers") or []):
        return "SATELLITE"
    return "UNCLASSIFIED"


def _portfolio_row(ticker: str) -> Dict[str, Any]:
    for row in _load(PORTFOLIO, []):
        if row.get("ticker") == ticker:
            return row
    return {}


def _snapshot_signals(ticker: str) -> Dict[str, Any]:
    active = _load(ACTIVE, {})
    action = (active.get("actions") or {}).get(ticker) or {}
    liq = active.get("liquidity_gate") or {}
    lve = active.get("liquidity_vector_engine") or {}
    prem = (_load(PREMIUM, {}).get("tickers") or {}).get(ticker) or {}
    th_rec = (_load(THESIS_HIST, {}) or {}).get(ticker) or {}
    fc_rec = (_load(FORECASTS, {"tickers": {}}).get("tickers") or {}).get(ticker) or {}
    return {
        "verb": action.get("verb"),
        "reason": action.get("reason"),
        "blocks": action.get("blocks") or [],
        "vetoes": action.get("vetoes") or [],
        "god_score": (_portfolio_row(ticker) or {}).get("god_score"),
        "ops": prem.get("ops") or action.get("ops"),
        "ops_band": prem.get("band") or action.get("ops_band"),
        "liquidity_zone": liq.get("zone"),
        "liquidity_vector_state": liq.get("vector_state_id") or lve.get("state_id"),
        "liquidity_vector_title": liq.get("vector_title") or lve.get("state_title"),
        "freeze_adds": liq.get("freeze_adds"),
        "thesis": action.get("thesis") or th_rec.get("thesis"),
        "ev_pct": action.get("ev_pct"),
        "es5_pct": action.get("es5_pct"),
        "p_win": action.get("p_win"),
        "conviction": action.get("conviction"),
        "size_pct_nav": action.get("size_pct_nav"),
        "forecast_source": action.get("forecast_source"),
        "forecast_weights": action.get("forecast_weights"),
        "forecast_quantiles": {
            "p05": fc_rec.get("ensemble", {}).get("p05"),
            "p25": fc_rec.get("ensemble", {}).get("p25"),
            "p50": fc_rec.get("ensemble", {}).get("p50"),
            "p75": fc_rec.get("ensemble", {}).get("p75"),
            "p95": fc_rec.get("ensemble", {}).get("p95"),
            "ev_pct": fc_rec.get("ensemble", {}).get("ev_pct"),
            "es5_pct": fc_rec.get("ensemble", {}).get("es5_pct"),
        },
        "per_model_forecasts": {
            m: fc_rec.get(m) for m in ("gem", "analog", "ml") if fc_rec.get(m)
        },
    }


def _annualised(total_return: float, holding_days: int) -> float:
    if holding_days <= 0:
        return 0.0
    d = max(1, holding_days)
    try:
        return (1.0 + total_return) ** (365.0 / d) - 1.0
    except Exception:
        return total_return


def close_trade(
    ticker: str,
    exit_price: float,
    *,
    opened_utc: Optional[str] = None,
    closed_utc: Optional[str] = None,
    entry_price: Optional[float] = None,
    currency: str = "USD",
    thesis_outcome: str = "timed_out",
    category: str = "unclassified",
    what_fired_first: Optional[str] = None,
    what_was_right: Optional[List[str]] = None,
    what_was_wrong: Optional[List[str]] = None,
    what_was_silent: Optional[List[str]] = None,
    felt: str = "",
    lessons_applied: Optional[List[str]] = None,
    max_drawdown_pct: Optional[float] = None,
    override: bool = False,
) -> Dict[str, Any]:
    """Write a lesson card. Returns the written payload."""
    os.makedirs(LESSONS_DIR, exist_ok=True)

    prow = _portfolio_row(ticker)
    entry_price = float(entry_price if entry_price is not None else (prow.get("entry_price") or 0.0))
    exit_price = float(exit_price)
    closed_utc = closed_utc or _now_iso()

    if not opened_utc:
        opened_utc = prow.get("opened_utc") or prow.get("entry_date") or closed_utc
    try:
        od = datetime.fromisoformat(str(opened_utc).replace("Z", "+00:00"))
        cd = datetime.fromisoformat(str(closed_utc).replace("Z", "+00:00"))
        holding_days = max(0, (cd - od).days)
    except Exception:
        holding_days = 0

    realized = (exit_price / entry_price - 1.0) if entry_price else 0.0
    realized_1y = _annualised(realized, holding_days)

    card_id = f"{ticker}_{closed_utc[:10]}"
    out_path = os.path.join(LESSONS_DIR, f"{card_id}.json")
    if os.path.exists(out_path) and not override:
        return _load(out_path, {})

    signals = _snapshot_signals(ticker)
    payload = {
        "schema_version": 1,
        "id": card_id,
        "ticker": ticker,
        "group": _group_for(ticker),
        "opened_utc": opened_utc,
        "closed_utc": closed_utc,
        "holding_days": holding_days,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "currency": currency,
        "realized_return": round(realized, 4),
        "realized_return_1y": round(realized_1y, 4),
        "max_drawdown_during_hold": max_drawdown_pct,
        "thesis_outcome": thesis_outcome,
        "category": category,
        "signals_at_entry": signals,
        "signals_at_exit": signals,
        "forecasts": signals.get("per_model_forecasts") or {},
        "ensemble_forecast_at_entry": signals.get("forecast_quantiles"),
        "what_fired_first": what_fired_first or "",
        "what_was_right": what_was_right or [],
        "what_was_wrong": what_was_wrong or [],
        "what_was_silent": what_was_silent or [],
        "felt": felt,
        "lessons_applied": lessons_applied or [],
        "recorded_utc": _now_iso(),
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    # Refresh the compact index
    write_index()
    return payload


def write_index() -> Dict[str, Any]:
    """Collapse all lesson cards into one compact feed for the dashboard."""
    rows = []
    for path in sorted(glob.glob(os.path.join(LESSONS_DIR, "*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                card = json.load(f)
            rows.append({
                "id": card.get("id"),
                "ticker": card.get("ticker"),
                "closed_utc": card.get("closed_utc"),
                "holding_days": card.get("holding_days"),
                "realized_return": card.get("realized_return"),
                "realized_return_1y": card.get("realized_return_1y"),
                "group": card.get("group"),
                "category": card.get("category"),
                "thesis_outcome": card.get("thesis_outcome"),
                "what_fired_first": card.get("what_fired_first"),
                "ops_at_entry": (card.get("signals_at_entry") or {}).get("ops"),
                "ev_pct_at_entry": (card.get("signals_at_entry") or {}).get("ev_pct"),
                "es5_pct_at_entry": (card.get("signals_at_entry") or {}).get("es5_pct"),
                "felt": card.get("felt"),
            })
        except Exception:
            continue

    rows.sort(key=lambda r: r.get("closed_utc") or "", reverse=True)

    cat_counts: Dict[str, int] = {}
    wins = losses = breakeven = 0
    pnl_pct_sum = 0.0
    for r in rows:
        cat = r.get("category") or "unclassified"
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
        rr = r.get("realized_return") or 0.0
        pnl_pct_sum += rr
        if rr > 0.01:
            wins += 1
        elif rr < -0.01:
            losses += 1
        else:
            breakeven += 1

    index = {
        "schema_version": 1,
        "generated_utc": _now_iso(),
        "count": len(rows),
        "summary": {
            "wins": wins,
            "losses": losses,
            "breakeven": breakeven,
            "avg_realized_pct": round((pnl_pct_sum / max(1, len(rows))) * 100.0, 2),
            "by_category": cat_counts,
        },
        "rows": rows,
    }

    out_path = os.path.join(BASE, "data", "lessons_index.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)

    try:
        import shutil
        shutil.copy2(out_path, WEBROOT_LESSONS_INDEX)
    except Exception:
        pass

    return index


def _cli() -> None:
    ap = argparse.ArgumentParser(description="Record a closed-trade lesson card.")
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--exit", type=float, required=True, help="Exit price")
    ap.add_argument("--entry", type=float, default=None, help="Entry price (defaults to portfolio_all)")
    ap.add_argument("--opened", default=None, help="Open UTC (ISO) — defaults to portfolio entry_date")
    ap.add_argument("--closed", default=None, help="Close UTC (ISO) — defaults to now")
    ap.add_argument("--currency", default="USD")
    ap.add_argument("--outcome", default="timed_out",
                    choices=["right", "wrong", "partial", "dead", "timed_out"])
    ap.add_argument("--category", default="unclassified",
                    help="premium_trap / thesis_rot / stop_bounce / harvest_win / ...")
    ap.add_argument("--fired-first", default="", help="Which signal warned first?")
    ap.add_argument("--right", nargs="*", default=[])
    ap.add_argument("--wrong", nargs="*", default=[])
    ap.add_argument("--silent", nargs="*", default=[])
    ap.add_argument("--felt", default="", help="Human reflection (behavioral gold)")
    ap.add_argument("--lesson", nargs="*", default=[], help="Lesson ID(s) from CLAUDE.md")
    ap.add_argument("--max-dd", type=float, default=None)
    ap.add_argument("--override", action="store_true", help="Overwrite existing card")
    args = ap.parse_args()

    card = close_trade(
        ticker=args.ticker,
        exit_price=args.exit,
        entry_price=args.entry,
        opened_utc=args.opened,
        closed_utc=args.closed,
        currency=args.currency,
        thesis_outcome=args.outcome,
        category=args.category,
        what_fired_first=args.fired_first or None,
        what_was_right=args.right,
        what_was_wrong=args.wrong,
        what_was_silent=args.silent,
        felt=args.felt,
        lessons_applied=args.lesson,
        max_drawdown_pct=args.max_dd,
        override=args.override,
    )
    print(json.dumps({"id": card.get("id"), "realized_return": card.get("realized_return"),
                      "outcome": card.get("thesis_outcome"), "category": card.get("category")},
                     indent=2))


if __name__ == "__main__":
    _cli()

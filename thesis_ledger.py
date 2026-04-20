"""
thesis_ledger.py — OLYMPUS decision journal with behavioural feedback.

Why this module exists:
  Institutions cannot do per-individual decision journals because committees
  anonymize ownership and LP scrutiny enforces short horizons. A solo
  investor with discipline CAN — and every logged decision compounds into
  better future conviction sizing.

Schema (data/thesis_ledger.json):
  {
    "decisions": [
      {
        "id": "uuid",
        "ticker": "NVDA",
        "action": "BUY" | "SELL" | "TRIM" | "ADD" | "SKIP",
        "date": "2025-11-15",
        "price": 135.0,
        "size_pct": 8.0,                        # % of portfolio (optional)
        "thesis": "Blackwell ramp drives $200B TAM; CUDA moat",
        "catalyst": "Q1 FY26 earnings May 28 — expecting beat+raise",
        "horizon": "3Y",
        "conviction": 8,                        # 1-10
        "target": 250.0,
        "stop_loss": 95.0,
        "exit_criteria": "CUDA moat erosion OR hits $250",
        "thesis_type": "ai_infra",              # free-form category
        "status": "open" | "closed",
        "thesis_last_reviewed": "2026-04-20",
        "exit_date": null,
        "exit_price": null,
        "exit_reason": null,
        "pnl_pct": null,
        "notes": ["2026-01-12: guide raised, thesis intact"]
      }
    ],
    "meta": { "created": "...", "last_written": "..." }
  }

CLI:
  python3 thesis_ledger.py add TICKER ACTION PRICE \
       --thesis "..." --catalyst "..." --horizon 3Y --conviction 8 \
       --target 250 --stop 95 --exit "thesis breach" --type ai_infra
  python3 thesis_ledger.py exit  TICKER PRICE --reason "..."
  python3 thesis_ledger.py note  TICKER "text"
  python3 thesis_ledger.py review TICKER    # updates thesis_last_reviewed
  python3 thesis_ledger.py list  [--closed|--all]
  python3 thesis_ledger.py hit-rate
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional

BASE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(BASE, "data", "thesis_ledger.json")


# ─────────────────────────── STORAGE ───────────────────────────
def _load() -> Dict[str, Any]:
    if not os.path.exists(LEDGER):
        return {"decisions": [], "meta": {"created": _now_iso(), "last_written": _now_iso()}}
    try:
        with open(LEDGER, encoding="utf-8") as f:
            d = json.load(f)
        d.setdefault("decisions", [])
        d.setdefault("meta", {})
        return d
    except Exception:
        return {"decisions": [], "meta": {"created": _now_iso(), "last_written": _now_iso()}}


def _save(d: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    d["meta"]["last_written"] = _now_iso()
    tmp = LEDGER + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
    os.replace(tmp, LEDGER)
    # Best-effort publish to dashboard webroot on servers that have it
    try:
        import shutil
        dest = "/var/www/html/ledger.json"
        if os.path.isdir(os.path.dirname(dest)):
            shutil.copy2(LEDGER, dest)
    except Exception:
        pass


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _today() -> str:
    return date.today().isoformat()


# ─────────────────────────── CORE OPS ───────────────────────────
VALID_ACTIONS = {"BUY", "SELL", "TRIM", "ADD", "SKIP"}


def add_decision(
    ticker: str,
    action: str,
    price: float,
    *,
    thesis: str,
    catalyst: str = "",
    horizon: str = "1Y",
    conviction: int = 5,
    target: Optional[float] = None,
    stop_loss: Optional[float] = None,
    exit_criteria: str = "",
    thesis_type: str = "",
    size_pct: Optional[float] = None,
    when: Optional[str] = None,
) -> Dict[str, Any]:
    action = action.upper().strip()
    if action not in VALID_ACTIONS:
        raise ValueError(f"action must be one of {VALID_ACTIONS}")
    if not thesis:
        raise ValueError("thesis is required — no anonymous bets")
    rec = {
        "id": uuid.uuid4().hex[:12],
        "ticker": ticker.upper().strip(),
        "action": action,
        "date": when or _today(),
        "price": float(price),
        "size_pct": float(size_pct) if size_pct is not None else None,
        "thesis": thesis.strip(),
        "catalyst": catalyst.strip(),
        "horizon": horizon.strip().upper(),
        "conviction": max(1, min(10, int(conviction))),
        "target": float(target) if target is not None else None,
        "stop_loss": float(stop_loss) if stop_loss is not None else None,
        "exit_criteria": exit_criteria.strip(),
        "thesis_type": thesis_type.strip().lower(),
        "status": "open" if action in {"BUY", "ADD"} else ("closed" if action in {"SELL", "SKIP"} else "open"),
        "thesis_last_reviewed": _today(),
        "exit_date": None,
        "exit_price": None,
        "exit_reason": None,
        "pnl_pct": None,
        "notes": [],
    }
    d = _load()
    d["decisions"].append(rec)
    _save(d)
    return rec


def exit_position(ticker: str, price: float, *, reason: str, when: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Close the oldest-open decision on this ticker, compute P&L."""
    d = _load()
    tk = ticker.upper().strip()
    open_decisions = [r for r in d["decisions"] if r["ticker"] == tk and r.get("status") == "open"]
    if not open_decisions:
        return None
    rec = open_decisions[0]
    rec["status"] = "closed"
    rec["exit_date"] = when or _today()
    rec["exit_price"] = float(price)
    rec["exit_reason"] = reason.strip()
    try:
        rec["pnl_pct"] = round(100.0 * (rec["exit_price"] / rec["price"] - 1.0), 2)
    except Exception:
        rec["pnl_pct"] = None
    _save(d)
    return rec


def add_note(ticker: str, text: str) -> Optional[Dict[str, Any]]:
    """Append a timestamped note to the most recent open decision."""
    d = _load()
    tk = ticker.upper().strip()
    open_decisions = [r for r in d["decisions"] if r["ticker"] == tk and r.get("status") == "open"]
    if not open_decisions:
        return None
    rec = open_decisions[-1]
    rec.setdefault("notes", []).append(f"{_today()}: {text.strip()}")
    rec["thesis_last_reviewed"] = _today()
    _save(d)
    return rec


def mark_reviewed(ticker: str) -> Optional[Dict[str, Any]]:
    d = _load()
    tk = ticker.upper().strip()
    hit = None
    for rec in d["decisions"]:
        if rec["ticker"] == tk and rec.get("status") == "open":
            rec["thesis_last_reviewed"] = _today()
            hit = rec
    if hit:
        _save(d)
    return hit


def list_open() -> List[Dict[str, Any]]:
    d = _load()
    return [r for r in d["decisions"] if r.get("status") == "open"]


def list_closed() -> List[Dict[str, Any]]:
    d = _load()
    return [r for r in d["decisions"] if r.get("status") == "closed"]


def all_decisions() -> List[Dict[str, Any]]:
    return _load()["decisions"]


def hit_rate() -> Dict[str, Any]:
    """Analytics on closed decisions: win rate, avg winner/loser, by thesis_type."""
    closed = [r for r in list_closed() if r.get("pnl_pct") is not None]
    if not closed:
        return {"n": 0}
    wins = [r for r in closed if (r.get("pnl_pct") or 0) > 0]
    losses = [r for r in closed if (r.get("pnl_pct") or 0) <= 0]
    by_type: Dict[str, Dict[str, Any]] = {}
    for r in closed:
        t = r.get("thesis_type") or "unclassified"
        bt = by_type.setdefault(t, {"n": 0, "wins": 0, "pnl": []})
        bt["n"] += 1
        bt["pnl"].append(r.get("pnl_pct") or 0)
        if (r.get("pnl_pct") or 0) > 0:
            bt["wins"] += 1
    for t, bt in by_type.items():
        bt["win_rate"] = round(bt["wins"] / bt["n"], 2) if bt["n"] else 0
        bt["avg_pnl"] = round(sum(bt["pnl"]) / len(bt["pnl"]), 2) if bt["pnl"] else 0
    return {
        "n": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(closed), 2),
        "avg_winner_pct": round(sum(r["pnl_pct"] for r in wins) / len(wins), 2) if wins else 0,
        "avg_loser_pct": round(sum(r["pnl_pct"] for r in losses) / len(losses), 2) if losses else 0,
        "by_thesis_type": by_type,
    }


# ─────────────────────────── CLI ───────────────────────────
def _cli_add(args: argparse.Namespace) -> int:
    rec = add_decision(
        args.ticker, args.action, args.price,
        thesis=args.thesis, catalyst=args.catalyst or "",
        horizon=args.horizon, conviction=args.conviction,
        target=args.target, stop_loss=args.stop,
        exit_criteria=args.exit or "", thesis_type=args.type or "",
        size_pct=args.size, when=args.date,
    )
    print(f"[LEDGER] {rec['action']} {rec['ticker']} @ {rec['price']} · conv {rec['conviction']}/10 · id {rec['id']}")
    return 0


def _cli_exit(args: argparse.Namespace) -> int:
    rec = exit_position(args.ticker, args.price, reason=args.reason, when=args.date)
    if not rec:
        print(f"[LEDGER] no open position for {args.ticker}")
        return 1
    print(f"[LEDGER] EXIT {rec['ticker']} @ {rec['exit_price']} · P&L {rec['pnl_pct']:+.2f}%")
    return 0


def _cli_note(args: argparse.Namespace) -> int:
    rec = add_note(args.ticker, args.text)
    if not rec:
        print(f"[LEDGER] no open position for {args.ticker}")
        return 1
    print(f"[LEDGER] note added to {rec['ticker']} ({len(rec['notes'])} total)")
    return 0


def _cli_review(args: argparse.Namespace) -> int:
    rec = mark_reviewed(args.ticker)
    if not rec:
        print(f"[LEDGER] no open position for {args.ticker}")
        return 1
    print(f"[LEDGER] {args.ticker} thesis_last_reviewed = {rec['thesis_last_reviewed']}")
    return 0


def _cli_list(args: argparse.Namespace) -> int:
    if args.closed:
        rows = list_closed()
    elif args.all:
        rows = all_decisions()
    else:
        rows = list_open()
    for r in rows:
        tail = ""
        if r.get("status") == "closed":
            tail = f" → exit {r.get('exit_price')} · P&L {r.get('pnl_pct')}%"
        print(f"{r['date']} {r['action']:4} {r['ticker']:<10} @ {r['price']:>10}  conv {r['conviction']}/10  "
              f"{r.get('thesis_type') or '—':<12}  {r['thesis'][:60]}{tail}")
    print(f"\n[{len(rows)} decisions]")
    return 0


def _cli_hitrate(args: argparse.Namespace) -> int:
    hr = hit_rate()
    print(json.dumps(hr, indent=2, ensure_ascii=False))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="thesis_ledger")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add")
    a.add_argument("ticker"); a.add_argument("action"); a.add_argument("price", type=float)
    a.add_argument("--thesis", required=True); a.add_argument("--catalyst", default="")
    a.add_argument("--horizon", default="1Y"); a.add_argument("--conviction", type=int, default=5)
    a.add_argument("--target", type=float); a.add_argument("--stop", type=float)
    a.add_argument("--exit", default=""); a.add_argument("--type", default="")
    a.add_argument("--size", type=float); a.add_argument("--date")
    a.set_defaults(func=_cli_add)

    e = sub.add_parser("exit")
    e.add_argument("ticker"); e.add_argument("price", type=float)
    e.add_argument("--reason", required=True); e.add_argument("--date")
    e.set_defaults(func=_cli_exit)

    n = sub.add_parser("note")
    n.add_argument("ticker"); n.add_argument("text")
    n.set_defaults(func=_cli_note)

    r = sub.add_parser("review"); r.add_argument("ticker"); r.set_defaults(func=_cli_review)

    l = sub.add_parser("list")
    l.add_argument("--closed", action="store_true"); l.add_argument("--all", action="store_true")
    l.set_defaults(func=_cli_list)

    h = sub.add_parser("hit-rate"); h.set_defaults(func=_cli_hitrate)

    args = p.parse_args()
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())

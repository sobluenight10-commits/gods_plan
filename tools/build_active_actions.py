"""
Single source of truth for "what to do per ticker RIGHT NOW".

Builds data/active_actions.json from the authoritative inputs:
  - portfolio_all.json (entry prices, overrides)
  - directives.json (strategic BUY/HOLD/WATCH list + liquidity zone)
  - thesis_history.json (guard-enforced thesis state)
  - catalyst_radar.json (upcoming events that override noise)

Every dashboard panel (Master Matrix, Soros panel, Radar, Telegram brief)
MUST read from this file, not from its own computation. That way the
"Soros=HOLD, Matrix=ADD" contradiction becomes impossible by construction.

Schema:
{
  "generated_utc": "...",
  "liquidity_gate": {"zone": "DANGER"|"WARNING"|..., "freeze_adds": bool},
  "actions": {
    "KTOS": {
      "verb": "HOLD",              # HOLD / ADD / TRIM / EXIT / WATCH / BUY
      "limit_price": null | float, # for BUY/ADD only
      "currency": "USD"|"EUR"|...,
      "reason": "thesis INTACT, sector pullback, earnings May 6",
      "horizon_note": "no ADD until May 6 earnings print",
      "thesis": "intact"|"wounded"|"dead",
      "blocks": ["liquidity_danger", "pending_catalyst", ...]
    }
  }
}
"""

import glob
import json
import os
import sys
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from kernel.prime_directive import evaluate_portfolio, invariants as kernel_invariants  # noqa: E402
from risk.drawdown_guardian import evaluate as evaluate_dd  # noqa: E402
from risk.position_sizer import size_position  # noqa: E402

PORTFOLIO = os.path.join(BASE, "gem_inputs", "portfolio_all.json")
DIRECTIVES = os.path.join(BASE, "data", "directives.json")
THESIS_HIST = os.path.join(BASE, "data", "thesis_history.json")
RADAR = os.path.join(BASE, "data", "catalyst_radar.json")
PREMIUM = os.path.join(BASE, "data", "premium_scores.json")
FORECASTS = os.path.join(BASE, "data", "forecasts.json")
STATE = os.path.join(BASE, "state.json")
GEM_DIR = os.path.join(BASE, "gem_results")
OUT = os.path.join(BASE, "data", "active_actions.json")
WEBROOT_OUT = "/var/www/html/active_actions.json"


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _latest_gem_alerts():
    """Return dict[ticker] -> gem row from the newest gem_results/gem_*.json file."""
    try:
        files = sorted(glob.glob(os.path.join(GEM_DIR, "gem_*.json")))
        if not files:
            return {}
        with open(files[-1], encoding="utf-8") as f:
            data = json.load(f)
        out = {}
        for row in data.get("alerts", []) or []:
            tk = row.get("ticker")
            if tk:
                out[tk] = row
        return out
    except Exception:
        return {}


def build():
    portfolio = _load(PORTFOLIO, [])
    directives = _load(DIRECTIVES, {})
    thesis_hist = _load(THESIS_HIST, {})
    radar = _load(RADAR, {"events": []})
    state_file = _load(STATE, {})
    gem_alerts = _latest_gem_alerts()
    forecasts = _load(FORECASTS, {"tickers": {}}).get("tickers", {})

    liq = directives.get("liquidity", {})
    zone = liq.get("zone", "NORMAL")
    direction = liq.get("direction") or "EXPANDING"
    lve = liq.get("liquidity_vector_engine") or {}
    sid = lve.get("state_id")
    # Vector Liquidity v2: freeze broad BUYs in states 1,4,6 — never in state 2 (strike window)
    if sid is not None:
        freeze_adds = sid in (1, 4, 6)
    else:
        freeze_adds = zone == "DANGER" or (
            zone == "WARNING" and direction == "CONTRACTING"
        )

    # Index strategic actions from directives.json (explicit user intent wins)
    strategic = {}
    for a in directives.get("actions", []):
        if isinstance(a, dict) and a.get("ticker"):
            strategic[a["ticker"]] = a

    # Index upcoming catalysts per ticker (earnings lock in HOLD)
    upcoming_earnings = {}
    today = datetime.now(timezone.utc).date()
    for ev in radar.get("events", []):
        tk = ev.get("ticker")
        if not tk:
            continue
        ev_date_str = ev.get("date") or ev.get("event_date")
        if not ev_date_str:
            continue
        try:
            ev_date = datetime.fromisoformat(str(ev_date_str)[:10]).date()
        except Exception:
            continue
        days_to = (ev_date - today).days
        if 0 <= days_to <= 14 and ev.get("event") in ("earnings", "EARNINGS"):
            if tk not in upcoming_earnings or days_to < upcoming_earnings[tk]["days"]:
                upcoming_earnings[tk] = {"days": days_to, "date": str(ev_date)}

    actions = {}
    for pos in portfolio:
        tk = pos.get("ticker")
        if not tk:
            continue

        # Thesis state — guard-enforced
        th_record = thesis_hist.get(tk, {})
        thesis = th_record.get("thesis") or pos.get("thesis_status", "intact")

        # Block reasons stack up
        blocks = []

        # 1. Explicit override wins over everything
        override = pos.get("action_override")
        if override:
            verb = override.split()[0].upper() if override.split() else "HOLD"
            actions[tk] = {
                "verb": verb,
                "limit_price": None,
                "currency": "USD",
                "reason": override,
                "horizon_note": pos.get("earnings_date")
                and f"earnings {pos['earnings_date']}"
                or "",
                "thesis": thesis,
                "blocks": ["explicit_override"],
                "source": "portfolio_all.action_override",
            }
            continue

        # 2. Strategic directive from directives.json
        if tk in strategic:
            d = strategic[tk]
            verb = (d.get("type") or "HOLD").upper()
            reason = d.get("reason", "")
            # Parse limit price from reason
            limit = None
            currency = "USD"
            import re

            m = re.search(r"\$(\d+(?:\.\d+)?)", reason)
            if m:
                limit = float(m.group(1))
                currency = "USD"
            else:
                m = re.search(r"€(\d+(?:\.\d+)?)", reason)
                if m:
                    limit = float(m.group(1))
                    currency = "EUR"

            # Liquidity freeze veto on new BUY
            if verb == "BUY" and freeze_adds:
                blocks.append(f"liquidity_{zone.lower()}_freeze")
                actions[tk] = {
                    "verb": "WATCH",
                    "limit_price": limit,
                    "currency": currency,
                    "reason": f"{reason} — BUT blocked: liquidity {zone}/{direction}",
                    "horizon_note": "await liquidity rebuild before arming",
                    "thesis": thesis,
                    "blocks": blocks,
                    "source": "directives+liquidity_gate",
                }
                continue

            actions[tk] = {
                "verb": verb,
                "limit_price": limit,
                "currency": currency,
                "reason": reason,
                "horizon_note": "",
                "thesis": thesis,
                "blocks": blocks,
                "source": "directives",
            }
            continue

        # 3. Upcoming earnings → HOLD (no ADD/TRIM right before a print)
        if tk in upcoming_earnings:
            ue = upcoming_earnings[tk]
            actions[tk] = {
                "verb": "HOLD",
                "limit_price": None,
                "currency": "USD",
                "reason": f"earnings in {ue['days']}d — no adds/trims before print",
                "horizon_note": f"earnings {ue['date']}",
                "thesis": thesis,
                "blocks": ["pending_catalyst"],
                "source": "catalyst_radar_earnings_lock",
            }
            continue

        # 4. Thesis DEAD → forced EXIT
        if thesis == "dead":
            actions[tk] = {
                "verb": "EXIT",
                "limit_price": None,
                "currency": "USD",
                "reason": "thesis DEAD — guard-enforced exit",
                "horizon_note": "full exit at market",
                "thesis": "dead",
                "blocks": [],
                "source": "thesis_guard",
            }
            continue

        # 5. Default HOLD for portfolio members
        actions[tk] = {
            "verb": "HOLD",
            "limit_price": None,
            "currency": "USD",
            "reason": "thesis intact, no catalyst, no directive",
            "horizon_note": "",
            "thesis": thesis,
            "blocks": blocks,
            "source": "default",
        }

    prem = _load(PREMIUM, {})
    pt = prem.get("tickers") or {}
    for tk, a in actions.items():
        pr = pt.get(tk)
        if not pr:
            continue
        a["ops"] = pr.get("ops")
        a["ops_band"] = pr.get("band")
        a["ops_hint"] = pr.get("hint")
        if float(pr.get("ops") or 0) >= 180 and a.get("verb") in ("BUY", "ADD"):
            bl = list(a.get("blocks") or [])
            if "ops_extreme" not in bl:
                bl.append("ops_extreme")
            a["blocks"] = bl
            a["verb"] = "WATCH"
            a["reason"] = (
                (a.get("reason") or "directive")
                + " — BLOCKED: OPS≥180 (extreme premium vs peers). "
                "GEM 'cheap' vs DCF can still be expensive vs sector — wait for multiple compression or thesis catalyst."
            )
            a["source"] = (a.get("source") or "") + "+ops_gate"

    # =====================================================================
    # PHASE 1 SENTINEL STACK
    # Layer 3 Ring 5: Drawdown Guardian (portfolio-wide state)
    # Layer 0:        Prime Directive kernel (four invariants)
    # Layer 3 Ring 1: Position Sizer (per-ticker Kelly + CVaR)
    # =====================================================================
    dd = evaluate_dd(portfolio, history_pct=None)

    # Cash / dry powder → fraction of NAV. For Phase 1 we use state.json
    # dry_powder (EUR) vs a rough NAV proxy = €8,600 + powder. This is
    # deliberately conservative; a future upgrade will read real NAV.
    dp = (state_file.get("dry_powder") or {})
    powder_eur = float(dp.get("TR_EUR") or 0.0)
    book_proxy_eur = 8600.0  # GOD's disclosed book excluding powder
    nav_proxy = max(1.0, book_proxy_eur + powder_eur)
    cash_pct = max(0.0, powder_eur / nav_proxy)

    positions_for_kernel = [
        {
            "ticker": p.get("ticker"),
            "sector": p.get("sector"),
            # No explicit weights yet → equal-weighted proxy inside kernel
        }
        for p in portfolio
        if p.get("ticker")
    ]
    kernel_state = evaluate_portfolio(
        positions_for_kernel,
        cash_pct=cash_pct,
        drawdown_pct=dd.get("dd_pct"),
        # Weights are equal-weight proxies until state.json carries explicit
        # sizes — suppress I2/I3 so we don't emit false breaches. I1 (DD) and
        # I4 (cash) still fire because they depend on real numbers.
        suppress_structural_breaches=True,
    )

    # Kernel freeze dominates liquidity freeze
    if kernel_state.get("freeze_all"):
        freeze_adds = True

    # Per-ticker sizing enrichment
    portfolio_by_tk = {p.get("ticker"): p for p in portfolio if p.get("ticker")}
    headroom_per_position = 1.0 / max(1, len(portfolio_by_tk))  # rough equal share
    for tk, a in actions.items():
        gem_row = gem_alerts.get(tk)
        prow = portfolio_by_tk.get(tk)

        # If the ensemble forecast exists, synthesize a "virtual GEM row" for
        # the sizer — it speaks the same {projections.1y.upside_pct,worst_drop_pct,
        # bull_gain_pct} dialect, so we don't have to change the sizer interface.
        fc = forecasts.get(tk, {}).get("ensemble") or {}
        if fc:
            virtual_row = dict(gem_row or {})
            virtual_row.setdefault("current_price", prow.get("current_price") if prow else None)
            virtual_row.setdefault("entry_price", prow.get("entry_price") if prow else None)
            virtual_row.setdefault("god_score", prow.get("god_score") if prow else None)
            virtual_row["projections"] = {
                "1y": {
                    "upside_pct": fc.get("ev_pct", 0.0),
                    "worst_drop_pct": fc.get("es5_pct", -20.0),
                    "bull_gain_pct": round((fc.get("p95") or 0.3) * 100.0, 2),
                }
            }
            sizer_gem_row = virtual_row
        else:
            sizer_gem_row = gem_row

        sizer = size_position(
            ticker=tk,
            verb=a.get("verb", "HOLD"),
            gem_row=sizer_gem_row,
            portfolio_row=prow,
            ops=a.get("ops"),
            thesis=a.get("thesis") or "intact",
            liq_freeze=freeze_adds,
            dd_state=dd,
            kernel_headroom_pct=headroom_per_position,
        )
        # Merge vetoes into blocks (but never double-count)
        existing_blocks = list(a.get("blocks") or [])
        for v in sizer.get("vetoes") or []:
            if v not in existing_blocks:
                existing_blocks.append(v)
        a["blocks"] = existing_blocks
        a["ev_pct"] = sizer["ev_pct"]
        a["es5_pct"] = sizer["es5_pct"]
        a["p_win"] = sizer["p_win"]
        a["kelly_frac"] = sizer["kelly_frac"]
        a["size_pct_nav"] = sizer["size_pct_nav"]
        a["conviction"] = sizer["conviction"]
        a["stop_price"] = sizer["stop_price"]
        a["vetoes"] = sizer["vetoes"]
        a["forecast_source"] = fc.get("source") if fc else ("gem" if gem_row else "prior")
        a["forecast_weights"] = fc.get("weights_used") if fc else None
        # If kernel / guardian veto and the verb is expansionary, downgrade it.
        if sizer["vetoes"] and a.get("verb") in ("BUY", "ADD"):
            a["verb"] = "WATCH"
            if "sentinel_veto" not in a["blocks"]:
                a["blocks"].append("sentinel_veto")

    payload = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "liquidity_gate": {
            "zone": zone,
            "direction": direction,
            "freeze_adds": freeze_adds,
            "vector_state_id": sid,
            "vector_title": lve.get("state_title"),
        },
        "liquidity_vector_engine": lve,
        "so_what_mandate": liq.get("so_what_consolidated") or "",
        "kernel": {
            "invariants": kernel_invariants(),
            "breaches": kernel_state.get("breaches", []),
            "freeze_all": kernel_state.get("freeze_all", False),
            "reasons": kernel_state.get("reasons", []),
            "sector_weights": kernel_state.get("sector_weights", {}),
            "cash_pct": cash_pct,
            "nav_proxy_eur": nav_proxy,
            "powder_eur": powder_eur,
        },
        "drawdown_guardian": dd,
        "actions": actions,
        "ticker_count": len(actions),
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    # Mirror to webroot so the dashboard reads it directly
    try:
        import shutil
        os.makedirs(os.path.dirname(WEBROOT_OUT), exist_ok=True)
        shutil.copy2(OUT, WEBROOT_OUT)
    except Exception as e:
        print(f"[warn] webroot mirror failed: {e}")

    arrow = "->"  # ASCII for Windows consoles; UTF-8 everywhere else is cosmetic.
    try:
        print(f"built {OUT}: {len(actions)} tickers · liquidity {zone}/{direction} · freeze={freeze_adds}")
        print(
            f"  kernel breaches: {kernel_state.get('breaches') or '[]'} · "
            f"DD {dd.get('state')}/{(dd.get('dd_pct') or 0)*100:.1f}% · "
            f"cash {cash_pct*100:.1f}%"
        )
        for tk, a in actions.items():
            if a.get("blocks") or a.get("vetoes"):
                all_blocks = list(a.get("blocks") or []) + list(a.get("vetoes") or [])
                print(
                    f"  {tk:10s} {arrow} {a['verb']:5s}  "
                    f"ev={a.get('ev_pct')}% es5={a.get('es5_pct')}% "
                    f"size={a.get('size_pct_nav')}%  blocks=[{','.join(all_blocks)}]"
                )
    except UnicodeEncodeError:
        pass
    return payload


if __name__ == "__main__":
    build()

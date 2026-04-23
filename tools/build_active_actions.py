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

import json
import os
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORTFOLIO = os.path.join(BASE, "gem_inputs", "portfolio_all.json")
DIRECTIVES = os.path.join(BASE, "data", "directives.json")
THESIS_HIST = os.path.join(BASE, "data", "thesis_history.json")
RADAR = os.path.join(BASE, "data", "catalyst_radar.json")
OUT = os.path.join(BASE, "data", "active_actions.json")
WEBROOT_OUT = "/var/www/html/active_actions.json"


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def build():
    portfolio = _load(PORTFOLIO, [])
    directives = _load(DIRECTIVES, {})
    thesis_hist = _load(THESIS_HIST, {})
    radar = _load(RADAR, {"events": []})

    liq = directives.get("liquidity", {})
    zone = liq.get("zone", "NORMAL")
    direction = liq.get("direction", "EXPANDING")
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

    payload = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "liquidity_gate": {
            "zone": zone,
            "direction": direction,
            "freeze_adds": freeze_adds,
        },
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

    print(f"built {OUT}: {len(actions)} tickers · liquidity {zone}/{direction} · freeze={freeze_adds}")
    # Show conflicts that were resolved (for audit)
    for tk, a in actions.items():
        if a["blocks"]:
            print(f"  {tk:10s} → {a['verb']:5s} (blocks: {','.join(a['blocks'])})")
    return payload


if __name__ == "__main__":
    build()

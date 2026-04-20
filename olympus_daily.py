"""olympus_daily.py — single entry point for OLYMPUS pipeline

Pipeline order:
  1. FRED liquidity refresh (prevents stale dashboard like Apr 14 incident)
  2. Fetch prices + macro + ranto posts
  3. Run engine (scoring, actions)
  4. Generate outputs (dashboard_state.json + Telegram brief)
  5. GEM grade-change digest (daily ranking diff → Telegram)
"""
import sys, os
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)


def _refresh_fred_liquidity() -> None:
    """Pull latest FRED reserves/TGA/RRP into data/directives.json."""
    try:
        from battle_rhythm import fetch_fred_liquidity
        out = fetch_fred_liquidity()
        net = (out or {}).get("net_liq_value") or (out or {}).get("net")
        print(f"[FRED] refresh OK: net_liq ≈ ${net}B" if net else "[FRED] refresh ran")
    except Exception as exc:
        print(f"[FRED] refresh failed: {exc}")


def _enrich_catalysts() -> None:
    """Pull Finnhub catalysts (next earnings, EPS-beat streak, analyst rec delta)."""
    try:
        from tools.catalyst_enricher import enrich_all
        enrich_all()
    except Exception as exc:
        print(f"[CATALYST] enrich failed: {exc}")


def _grade_diff_digest() -> None:
    """Run the GEM grade-change digest (silent if no new run today)."""
    try:
        from tools.gem_grade_diff import run as _run_digest
        _run_digest()
    except Exception as exc:
        print(f"[GEM_DIFF] digest failed: {exc}")


def main():
    print("=== OLYMPUS DAILY PIPELINE ===")
    _refresh_fred_liquidity()
    _enrich_catalysts()
    from fetch_data import get_all_data
    from olympus_engine import run_engine
    from output_factory import generate_outputs
    data = get_all_data()
    print(f"Data: {len(data['prices'])} prices, {len(data['universe'])} universe")
    state = run_engine(data)
    print(f"Engine: ONE COMMAND = {state['one_command'][:60]}")
    generate_outputs(state)
    _grade_diff_digest()
    print("=== DONE ===")


if __name__ == "__main__":
    main()

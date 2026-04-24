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


def _publish_ledger() -> None:
    """Copy thesis_ledger to /var/www/html/ledger.json for dashboard fetch."""
    try:
        from tools.publish_ledger import main as _pub
        _pub()
    except Exception as exc:
        print(f"[LEDGER] publish failed: {exc}")


def _run_premium_scores() -> None:
    """Sector-relative OPS (premium) — closes KTOS-style blind spot."""
    try:
        from tools.premium_score import main as _ops_main

        _ops_main()
    except Exception as exc:
        print(f"[OPS] failed: {exc}")


def _publish_premium_scores() -> None:
    try:
        import shutil

        src = os.path.join(BASE, "data", "premium_scores.json")
        if os.path.isfile(src):
            shutil.copy2(src, "/var/www/html/premium_scores.json")
            print("[OPS] published → webroot")
    except Exception as exc:
        print(f"[OPS] publish failed: {exc}")


def _publish_gem_meta() -> None:
    try:
        from tools.publish_gem_meta import main as _gem_meta

        _gem_meta()
    except Exception as exc:
        print(f"[GEM_META] failed: {exc}")


def _publish_core_satellite() -> None:
    try:
        import shutil

        src = os.path.join(BASE, "gem_inputs", "core_satellite.json")
        if os.path.isfile(src):
            shutil.copy2(src, "/var/www/html/core_satellite.json")
            print("[CORE] published core_satellite.json")
    except Exception as exc:
        print(f"[CORE] publish failed: {exc}")


def _publish_blog_tickers() -> None:
    """Ship blog / Kiwoom tactical_sleeve JSON for dashboard + forecaster merge."""
    try:
        import shutil

        src = os.path.join(BASE, "data", "blog_tickers.json")
        if not os.path.isfile(src):
            src = os.path.join(BASE, "gem_inputs", "blog_tickers.json")
        if not os.path.isfile(src):
            return
        shutil.copy2(src, "/var/www/html/blog_tickers.json")
        data_dir = "/var/www/html/data"
        os.makedirs(data_dir, exist_ok=True)
        shutil.copy2(src, os.path.join(data_dir, "blog_tickers.json"))
        print("[BLOG] published blog_tickers.json → webroot")
    except Exception as exc:
        print(f"[BLOG] publish failed: {exc}")


def _publish_watchlist_bench() -> None:
    """Ship watchlist_bench.json to webroot (research queue, not quota fills)."""
    try:
        import shutil
        src = os.path.join(BASE, "gem_inputs", "watchlist_bench.json")
        dst = "/var/www/html/watchlist_bench.json"
        if os.path.isfile(src):
            shutil.copy2(src, dst)
            print("[BENCH] published → webroot")
    except Exception as exc:
        print(f"[BENCH] publish failed: {exc}")


def _build_catalyst_radar() -> None:
    """Build unified catalyst radar (base rates + asymmetry + attention)."""
    try:
        from tools.catalyst_radar import build_radar
        build_radar()
    except Exception as exc:
        print(f"[RADAR] build failed: {exc}")


def _publish_catalyst_radar() -> None:
    """Ship catalyst radar JSON to the webroot."""
    try:
        from tools.catalyst_publish import main as _pub_radar
        _pub_radar()
    except Exception as exc:
        print(f"[RADAR] publish failed: {exc}")


def _catalyst_digest() -> None:
    """Send Telegram T-minus pre-event digest (silent if empty)."""
    try:
        from tools.catalyst_digest import run as _run_digest
        _run_digest(horizon=14)
    except Exception as exc:
        print(f"[RADAR] digest failed: {exc}")


def _run_forecasters() -> None:
    """Phase 2 forecaster ensemble: GEM + analog k-NN + OLS bootstrap."""
    try:
        from tools.run_forecasters import run as _run
        _run(force=False)
    except Exception as exc:
        print(f"[FORECASTERS] failed: {exc}")


def _refit_weights() -> None:
    """Phase 2 reflection: update forecaster weights from lesson cards."""
    try:
        from reflection.post_mortem import refit_weights
        refit_weights()
    except Exception as exc:
        print(f"[REFLECTION] refit failed: {exc}")


def _build_active_actions() -> None:
    """Single-source action layer — reconciles every panel to one truth."""
    try:
        from tools.build_active_actions import build
        build()
    except Exception as exc:
        print(f"[ACTIONS] build failed: {exc}")


def main():
    print("=== OLYMPUS DAILY PIPELINE ===")
    _refresh_fred_liquidity()
    _enrich_catalysts()
    _run_premium_scores()
    _publish_premium_scores()
    _publish_gem_meta()
    _publish_core_satellite()
    _publish_blog_tickers()
    from fetch_data import get_all_data
    from olympus_engine import run_engine
    from output_factory import generate_outputs
    data = get_all_data()
    print(f"Data: {len(data['prices'])} prices, {len(data['universe'])} universe")
    state = run_engine(data)
    print(f"Engine: ONE COMMAND = {state['one_command'][:60]}")
    generate_outputs(state)
    _grade_diff_digest()
    _publish_ledger()
    _publish_watchlist_bench()
    _build_catalyst_radar()
    _publish_catalyst_radar()
    _catalyst_digest()
    # Phase 2: reflection → ensemble forecasts → consumed by build_active_actions
    _refit_weights()
    _run_forecasters()
    # Must run LAST — consumes directives, portfolio, thesis_history, radar, forecasts
    _build_active_actions()
    print("=== DONE ===")


if __name__ == "__main__":
    main()

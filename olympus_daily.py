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
    """Pull latest FRED reserves/TGA/RRP into data/directives.json, then publish.

    A silent failure here was what caused the April-14 liquidity to re-surface
    on the dashboard. We now (a) verify FRED returned all three series,
    (b) verify the file was rewritten, (c) mirror to /var/www/html/directives.json
    so both the local and nginx `/data/` alias routes stay consistent.
    """
    import json
    import shutil
    from datetime import datetime, timezone

    directives_local = os.path.join(BASE, "data", "directives.json")
    directives_web = "/var/www/html/directives.json"

    try:
        from battle_rhythm import fetch_fred_liquidity
        out = fetch_fred_liquidity() or {}
    except Exception as exc:  # noqa: BLE001
        print(f"[FRED] fetch failed: {exc}")
        return

    missing = [k for k in ("reserves", "tga", "rrp") if out.get(k) is None]
    if missing:
        print(f"[FRED] incomplete — missing {missing}. Directives NOT overwritten.")
        return

    try:
        with open(directives_local, "r", encoding="utf-8") as f:
            d = json.load(f)
        liq = (d or {}).get("liquidity") or {}
        net = liq.get("net_liq_b") or liq.get("net_liq_value")
        last = liq.get("last_updated")
        vel7 = liq.get("velocity_7d_b")
        zone = liq.get("zone")
        print(f"[FRED] refresh OK: net ${net}B · zone {zone} · 7d Δ {vel7}B · last_updated {last}")
    except Exception as exc:  # noqa: BLE001
        print(f"[FRED] post-write inspection failed: {exc}")

    try:
        if os.path.isfile(directives_local) and os.path.isdir(os.path.dirname(directives_web)):
            shutil.copy2(directives_local, directives_web)
            print(f"[FRED] mirrored -> {directives_web}")
    except Exception as exc:  # noqa: BLE001
        print(f"[FRED] webroot mirror failed: {exc}")


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


# ---------------------------------------------------------------------------
# PHASE 4 — DISCOVERY + REFLECTION + BEHAVIORAL + DEPLOY
# ---------------------------------------------------------------------------

def _insider_flow() -> None:
    """SEC EDGAR Form-4 cluster-buy detector."""
    try:
        from tools.insider_flow import run as _run
        _run()
    except Exception as exc:
        print(f"[INSIDER] failed: {exc}")


def _secular_trends() -> None:
    """8 civilisational themes, proxy-ETF alpha vs benchmark."""
    try:
        from tools.secular_trends import run as _run
        _run()
    except Exception as exc:
        print(f"[SECULAR] failed: {exc}")


def _patent_signal() -> None:
    """USPTO PatentsView velocity per theme + per ticker."""
    try:
        from tools.patent_signal import run as _run
        _run()
    except Exception as exc:
        print(f"[PATENT] failed: {exc}")


def _ipo_radar() -> None:
    """Upcoming IPOs + spinoffs scored against the 8 GOD sectors."""
    try:
        from tools.ipo_spinoff_radar import run as _run
        _run()
    except Exception as exc:
        print(f"[IPO] failed: {exc}")


def _lesson_roundup() -> None:
    """Weekly system-error digest across all lesson cards."""
    try:
        from tools.lesson_roundup import run as _run
        _run()
    except Exception as exc:
        print(f"[LESSONS] roundup failed: {exc}")


def _behavioral_publish() -> None:
    """Publish cooldowns + pending restatements + override patterns."""
    try:
        from behavioral.circuit_breakers import publish_state
        publish_state()
    except Exception as exc:
        print(f"[BEHAV] publish failed: {exc}")


def _deploy_optimiser() -> None:
    """Marginal Sharpe ranking for the €1,500/mo monthly deploy decision."""
    try:
        from tools.deploy_optimiser import run as _run
        _run()
    except Exception as exc:
        print(f"[DEPLOY] optimiser failed: {exc}")


def _scenario_engine() -> None:
    """Publish probability-weighted macro scenario expected values."""
    try:
        from tools.scenario_engine import run as _run
        _run()
        print("[SCENARIO] published")
    except Exception as exc:
        print(f"[SCENARIO] failed: {exc}")


def _strike_radar() -> None:
    """Multi-horizon liquidity vector pivot detector. Source of truth for STRIKE state."""
    try:
        from tools.strike_radar import run as _run
        out = _run()
        print(f"[STRIKE_RADAR] state={out.get('state')} score={out.get('strike_score')} "
              f"net=${out.get('net_liq_b')}B v_3d={(out.get('velocity_b_per_day') or {}).get('v_3d')} "
              f"v_7d={(out.get('velocity_b_per_day') or {}).get('v_7d')}")
    except Exception as exc:
        print(f"[STRIKE_RADAR] failed: {exc}")


def _strike_cards() -> None:
    """Per-ticker decisive composite — single 0-100 strike_score per name."""
    try:
        from tools.strike_cards import run as _run
        out = _run()
        print(f"[STRIKE_CARDS] {out.get('n_eligible')}/{out.get('n_total')} eligible · "
              f"top: " + ", ".join(c["ticker"] + f"({c['strike_score']})"
                                    for c in (out.get("shortlist") or [])[:5]))
    except Exception as exc:
        print(f"[STRIKE_CARDS] failed: {exc}")


def _strike_plan() -> None:
    """Three-tranche pyramid plan, gated by strike_radar state."""
    try:
        from tools.strike_plan import run as _run
        plan = _run()
        print(f"[STRIKE_PLAN] {plan.get('mandate')}")
    except Exception as exc:
        print(f"[STRIKE_PLAN] failed: {exc}")


def _point_a_scan() -> None:
    """Point A scanner — earliest reliable buy signal (macro-driven entry)."""
    try:
        from tools.point_a_scanner import run as _run
        out = _run()
        print(f"[POINT_A] fired={out.get('n_fired')} watch={out.get('n_watch')} · "
              f"A1={out.get('a1_liquidity_expanding',{}).get('value')} "
              f"A2={out.get('a2_funding_easing',{}).get('value')}")
    except Exception as exc:
        print(f"[POINT_A] failed: {exc}")


def _point_b_scan() -> None:
    """Point B scanner — Soros gap formalised (-15% from 20d high, base intact)."""
    try:
        from tools.point_b_scanner import run as _run
        out = _run()
        print(f"[POINT_B] execute={out.get('n_execute')} warning={out.get('n_warning')} "
              f"review={out.get('n_review')}")
    except Exception as exc:
        print(f"[POINT_B] failed: {exc}")


def _heads_up() -> None:
    """Consolidate Point A / Point B / proximity into the single Telegram-ready feed."""
    try:
        from tools.heads_up import run as _run
        out = _run(send_telegram=True)
        print(f"[HEADS_UP] {out.get('one_command')}")
    except Exception as exc:
        print(f"[HEADS_UP] failed: {exc}")


def _embed_dashboard_preload() -> None:
    """Inline JSON snapshot into OLYMPUS_UNIFIED.html (GitHub/file mirror safe)."""
    try:
        from tools.embed_dashboard_preload import run as _run
        _run()
    except Exception as exc:
        print(f"[EMBED] failed: {exc}")


def _publish_lessons_index() -> None:
    try:
        from tools import close_trade as _ct
        _ct.write_index()
        import shutil
        src = os.path.join(BASE, "data", "lessons_index.json")
        if os.path.isfile(src):
            shutil.copy2(src, "/var/www/html/lessons_index.json")
            print("[LESSONS] index published -> webroot")
    except Exception as exc:
        print(f"[LESSONS] publish failed: {exc}")


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
    # Must run BEFORE phase 4 modules that read active_actions.json
    _build_active_actions()
    # Phase 4 — DISCOVERY + REFLECTION + BEHAVIORAL + DEPLOY
    _insider_flow()
    _secular_trends()
    _patent_signal()
    _ipo_radar()
    _lesson_roundup()
    _publish_lessons_index()
    _behavioral_publish()
    _deploy_optimiser()
    # Phase 5 — STRIKE ENGINE (single decisive layer on top of everything else)
    _scenario_engine()
    _strike_radar()
    # Point A/B scanners run BEFORE strike_cards so each card can embed its
    # entry_ladder (best single + 3-tier price) sourced from point_b_scan.json.
    _point_a_scan()
    _point_b_scan()
    _strike_cards()
    _strike_plan()

    # Phase 6 — HEADS-UP (proximity-gated, Telegram-clean) — runs last so
    # it can read the latest strike_cards/strike_plan if needed.
    _heads_up()
    _embed_dashboard_preload()
    print("=== DONE ===")


if __name__ == "__main__":
    main()

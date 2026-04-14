"""run_skills.py — OLYMPUS Skills Pipeline Orchestrator.

Usage:
    python run_skills.py              # Run all daily skills (risk + fundamentals + sentiment)
    python run_skills.py --risk       # Run risk screener only
    python run_skills.py --fund       # Run financial analysis only
    python run_skills.py --sentiment  # Run news sentiment only
    python run_skills.py --weekly     # Run weekly skills (includes all daily + portfolio review)

Cron (add to server):
    30 5 * * 1-5 cd /root/gods_plan && python3 run_skills.py >> /var/log/olympus_skills.log 2>&1
"""
import argparse
import json
import logging
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

import pytz

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

BERLIN = pytz.timezone("Europe/Berlin")
RESULTS_DIR = BASE / "data" / "skill_results"
WEB_RESULTS = Path("/var/www/html/data/skill_results")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("olympus.skills.runner")


def _symlink_latest(results_dir: Path, prefix: str, dated_file: Path):
    """Create/update a _latest.json symlink/copy for the web server."""
    latest = results_dir / f"{prefix}_latest.json"
    try:
        if latest.exists() or latest.is_symlink():
            latest.unlink()
        shutil.copy2(str(dated_file), str(latest))
    except Exception as e:
        logger.warning(f"Could not create latest link for {prefix}: {e}")

    if WEB_RESULTS.parent.exists():
        WEB_RESULTS.mkdir(parents=True, exist_ok=True)
        web_latest = WEB_RESULTS / f"{prefix}_latest.json"
        try:
            shutil.copy2(str(dated_file), str(web_latest))
            logger.info(f"Copied to web: {web_latest}")
        except Exception as e:
            logger.warning(f"Web copy failed for {prefix}: {e}")


def run_risk():
    logger.info("=== RISK SCREENER ===")
    t0 = time.time()
    from skills.risk_screener import RiskScreener
    rs = RiskScreener()
    result = rs.run_all()
    summary = result.get("summary", {})
    critical = len(summary.get("critical", []))
    high = len(summary.get("high", []))
    logger.info(
        f"Risk done: {result['total']} tickers, "
        f"{critical} critical, {high} high, "
        f"avg={summary.get('portfolio_avg_risk', '?')}/9 "
        f"({time.time()-t0:.1f}s)"
    )
    today = datetime.now(BERLIN).strftime("%Y%m%d")
    dated = RESULTS_DIR / f"risk_{today}.json"
    _symlink_latest(RESULTS_DIR, "risk", dated)
    return result


def run_fundamentals():
    logger.info("=== FINANCIAL ANALYSIS ===")
    t0 = time.time()
    from skills.financial_analysis import FinancialAnalysis
    fa = FinancialAnalysis()
    result = fa.run_all()
    ok = sum(1 for r in result.get("results", {}).values() if not r.get("error"))
    logger.info(f"Fundamentals done: {ok}/{result['total']} tickers ({time.time()-t0:.1f}s)")
    today = datetime.now(BERLIN).strftime("%Y%m%d")
    dated = RESULTS_DIR / f"fundamentals_{today}.json"
    _symlink_latest(RESULTS_DIR, "fundamentals", dated)
    return result


def run_sentiment():
    logger.info("=== NEWS SENTIMENT ===")
    t0 = time.time()
    from skills.news_sentiment import NewsSentiment
    ns = NewsSentiment()
    result = ns.run_all()
    logger.info(
        f"Sentiment done: {result['total_tickers']} tickers, "
        f"{result['total_articles']} articles ({time.time()-t0:.1f}s)"
    )
    today = datetime.now(BERLIN).strftime("%Y%m%d")
    dated = RESULTS_DIR / f"sentiment_{today}.json"
    _symlink_latest(RESULTS_DIR, "sentiment", dated)
    return result


def main():
    parser = argparse.ArgumentParser(description="OLYMPUS Skills Pipeline")
    parser.add_argument("--risk", action="store_true", help="Run risk screener only")
    parser.add_argument("--fund", action="store_true", help="Run financial analysis only")
    parser.add_argument("--sentiment", action="store_true", help="Run news sentiment only")
    parser.add_argument("--weekly", action="store_true", help="Run all weekly skills")
    args = parser.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(BERLIN)
    logger.info(f"OLYMPUS Skills Pipeline — {now.strftime('%Y-%m-%d %H:%M')} Berlin")

    specific = args.risk or args.fund or args.sentiment

    if not specific or args.weekly:
        run_risk()
        run_fundamentals()
        run_sentiment()
        logger.info("=== ALL DAILY SKILLS COMPLETE ===")
    else:
        if args.risk:
            run_risk()
        if args.fund:
            run_fundamentals()
        if args.sentiment:
            run_sentiment()

    logger.info("Done.")


if __name__ == "__main__":
    main()

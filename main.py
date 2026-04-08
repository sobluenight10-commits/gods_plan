"""
🔱 titan_K v2 — Main Entry Point (v3 Upgrade)
Fixes: message duplication, timezone drift, slow responses, process conflicts.

Usage:
    python main.py              # Full system: bot + 9 scheduled briefings
    python main.py --test       # Send morning_macro briefing now
    python main.py --blog       # Send blog briefing now
    python main.py --macro      # Send macro briefing now
    python main.py --schedule   # Scheduler only (no interactive bot)
    python main.py --listen     # Interactive bot only (no scheduler)
    python main.py --ping       # Test Telegram connection
"""
import sys
import json
import os
import logging
import argparse
import threading
import time
import signal
from datetime import datetime
from pathlib import Path

import schedule
import pytz

import config as app_config

from config import (
    TIMEZONE,
    OPENAI_API_KEY,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    DATA_FILE,
    IMPORTANT_KEYWORDS,
    is_institutional_signal,
    BLOG_FETCH_INTERVAL_MINUTES,
)

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("titan_k.log", encoding="utf-8", errors="replace"),
    ],
)
logger = logging.getLogger("titan_k.main")

# Institutional headline filter: IMPORTANT_KEYWORDS + is_institutional_signal live in config.py
# (imported above). News pulse in battle_rhythm.py uses them to cut Telegram noise.

# ── Process Lock (prevents duplicate bots) ────────────────────────────────────
LOCK_FILE = Path("titan_k.lock")


def _acquire_lock():
    """Prevent multiple instances from running simultaneously."""
    if LOCK_FILE.exists():
        try:
            old_pid = int(LOCK_FILE.read_text().strip())
            # Check if process is still alive
            try:
                os.kill(old_pid, 0)
                logger.error(f"Another titan_K is running (PID {old_pid}). Kill it first:")
                logger.error(f"  taskkill /F /PID {old_pid}")
                sys.exit(1)
            except OSError:
                pass  # Old process is dead — stale lock
        except (ValueError, OSError):
            pass

    LOCK_FILE.write_text(str(os.getpid()))
    logger.info(f"Lock acquired (PID {os.getpid()})")


def _release_lock():
    try:
        if LOCK_FILE.exists():
            LOCK_FILE.unlink()
    except:
        pass


def _cleanup(signum=None, frame=None):
    logger.info("Shutting down...")
    _release_lock()
    sys.exit(0)


signal.signal(signal.SIGINT, _cleanup)
signal.signal(signal.SIGTERM, _cleanup)
import atexit
atexit.register(_release_lock)


# ── Config Validation ─────────────────────────────────────────────────────────
def validate_config():
    missing = []
    if not OPENAI_API_KEY or OPENAI_API_KEY.startswith("sk-your"):
        missing.append("OPENAI_API_KEY")
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN.startswith("your"):
        missing.append("TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_CHAT_ID or TELEGRAM_CHAT_ID.startswith("your"):
        missing.append("TELEGRAM_CHAT_ID")
    if missing:
        logger.error(f"Missing config: {', '.join(missing)}")
        sys.exit(1)
    logger.info("Config validated")


# ══════════════════════════════════════════════════════════════════════════════
# BRIEFING EXECUTION (with deduplication)
# ══════════════════════════════════════════════════════════════════════════════

_last_sent = {}


def run_briefing(briefing_id: str, description: str = ""):
    """Execute a briefing with deduplication guard."""
    now = _berlin_now()
    key = f"{briefing_id}_{now.strftime('%Y-%m-%d_%H')}"

    if key in _last_sent:
        logger.warning(f"SKIP duplicate: {briefing_id} already sent this hour")
        return

    logger.info(f"[{now.strftime('%H:%M Berlin')}] Running: {briefing_id}")

    if briefing_id == "blog":
        _run_blog()
    elif briefing_id in ("olympus", "olympus_weekly"):
        _run_olympus()
    elif briefing_id in ("master_daily", "us_open", "us_interim", "us_close"):
        _run_daily_brief(briefing_id)
    else:
        _run_battle_rhythm(briefing_id)

    _last_sent[key] = now.strftime("%H:%M")


def _run_blog():
    try:
        from scraper import fetch_blog_posts
        from analyzer import analyze_post, generate_blog_summary
        from telegram_bot import send_blog_briefing

        posts = fetch_blog_posts(days_back=1, max_posts=3)
        if not posts:
            posts = fetch_blog_posts(days_back=3, max_posts=3)
        if not posts:
            from telegram_bot import send_telegram
            send_telegram("🔱 📭 No new ranto28 posts in 3 days.")
            return

        analyses = [r for p in posts if not (r := analyze_post(p)).get("error")]
        summary = generate_blog_summary(analyses) if analyses else "Analysis failed."
        send_blog_briefing({
            "timestamp": _berlin_now().strftime("%Y-%m-%d %H:%M"),
            "posts": analyses, "summary": summary,
        })
        _save_analyses(analyses)
        logger.info(f"Blog sent: {len(analyses)} posts")
    except Exception as e:
        logger.error(f"Blog failed: {e}", exc_info=True)
        try:
            from telegram_bot import send_telegram
            send_telegram(f"🔱 ⚠️ Blog error: {str(e)[:200]}")
        except:
            pass


def _run_olympus():
    """Scheduled Olympus refresh. Telegram /olympus is handled in interactive_bot.cmd_olympus; both paths call run_olympus_update(), which writes data/directives.json."""
    try:
        from olympus_engine import run_olympus_update, get_olympus_telegram_summary
        from telegram_bot import send_telegram
        result = run_olympus_update()
        msg = get_olympus_telegram_summary(result)
        send_telegram(msg)
        logger.info("Olympus update sent")
    except Exception as e:
        logger.error(f"Olympus failed: {e}", exc_info=True)
        try:
            from telegram_bot import send_telegram
            send_telegram(f"🏛 Olympus error: {str(e)[:200]}")
        except:
            pass


def _run_battle_rhythm(briefing_id: str):
    try:
        from battle_rhythm import generate_briefing
        from telegram_bot import send_telegram
        msg = generate_briefing(briefing_id)
        if msg:
            send_telegram(msg)
            logger.info(f"{briefing_id} sent")
    except Exception as e:
        logger.error(f"{briefing_id} failed: {e}", exc_info=True)
        try:
            from telegram_bot import send_telegram
            send_telegram(f"🔱 ⚠️ {briefing_id} error: {str(e)[:200]}")
        except:
            pass


# ══════════════════════════════════════════════════════════════════════════════
# SCHEDULER (Berlin timezone — independent of system clock)
# ══════════════════════════════════════════════════════════════════════════════

def _setup_schedule():
    """Register briefings using schedule library with Berlin timezone."""
    from config import DAILY_SCHEDULE, WEEKLY_SCHEDULE
    schedule.clear()

    # Weekday briefings (weekday check enforced in generate_briefing)
    for sched_time, briefing_id, description in DAILY_SCHEDULE:
        schedule.every().day.at(sched_time, "Europe/Berlin").do(
            run_briefing, briefing_id, description
        )

    # Saturday Olympus
    for sched_time, briefing_id, description in WEEKLY_SCHEDULE:
        schedule.every().saturday.at(sched_time, "Europe/Berlin").do(
            run_briefing, briefing_id, description
        )

    # Layer 3 — news pulse (interval + Berlin window from config, see NEWS_PULSE_*)
    from battle_rhythm import run_news_pulse

    pulse_min = int(getattr(app_config, "NEWS_PULSE_INTERVAL_MINUTES", 120))
    pulse_min = max(15, pulse_min)
    schedule.every(pulse_min).minutes.do(run_news_pulse)
    p_start = getattr(app_config, "NEWS_PULSE_START_HOUR", 7.0)
    p_end = getattr(app_config, "NEWS_PULSE_END_HOUR", 23.5)

    from price_alert import check_thesis_alerts

    schedule.every(30).minutes.do(check_thesis_alerts)

    logger.info(
        "Registered %s daily + %s weekly + news pulse every %s min "
        "(Berlin window %s–%s) + thesis alerts every 30 min (weekdays 15:30–22:00 Berlin)",
        len(DAILY_SCHEDULE),
        len(WEEKLY_SCHEDULE),
        pulse_min,
        p_start,
        p_end,
    )


def _berlin_now():
    """Get current Berlin time."""
    return datetime.now(pytz.timezone(TIMEZONE))


def start_scheduler():
    from config import DAILY_SCHEDULE
    _setup_schedule()
    berlin = pytz.timezone(TIMEZONE)
    now = datetime.now(berlin)
    logger.info("=" * 50)
    logger.info(f"🔱 SCHEDULER ONLY — {now.strftime('%H:%M %Z')}")
    for t, _, desc in DAILY_SCHEDULE:
        logger.info(f"  ⏰ {t} {desc}")
    logger.info("=" * 50)

    from blog_monitor import start_blog_monitor
    start_blog_monitor()

    while True:
        schedule.run_pending()
        time.sleep(10)


def start_full_system():
    from config import DAILY_SCHEDULE
    _acquire_lock()
    _setup_schedule()
    berlin = pytz.timezone(TIMEZONE)
    now = datetime.now(berlin)
    logger.info("=" * 50)
    logger.info(f"🔱 FULL SYSTEM — {now.strftime('%H:%M %Z')}")
    logger.info(f"  📡 Bot: LISTENING")
    logger.info(f"  ⏰ {len(DAILY_SCHEDULE)} daily briefings")
    for t, _, desc in DAILY_SCHEDULE:
        logger.info(f"     {t} {desc}")
    logger.info("=" * 50)

    # Notify Telegram that Minerva is online (so user knows alarms will work)
    try:
        from telegram_bot import send_telegram
        lines = [
            "🔱 <b>Minerva ONLINE</b>",
            "Send /start for commands.",
            "",
            "<b>Berlin (weekdays)</b>",
            "· 07:00 Morning · 16:30 US Open · 19:00 Interim · 23:30 US Close",
            f"· News pulse every {int(getattr(app_config, 'NEWS_PULSE_INTERVAL_MINUTES', 120))} min "
            f"({getattr(app_config, 'NEWS_PULSE_START_HOUR', 7)}–{getattr(app_config, 'NEWS_PULSE_END_HOUR', 23.5)}h, filtered headlines)",
            "· Thesis -8% scan every 30 min (weekdays 15:30–22:00 Berlin, config THESIS_ALERT_TICKERS)",
            f"· Blog RSS every {BLOG_FETCH_INTERVAL_MINUTES} min (ranto28)",
        ]
        send_telegram("\n".join(lines))
    except Exception as e:
        logger.warning(f"Startup Telegram ping failed: {e}")

    def scheduler_loop():
        while True:
            schedule.run_pending()
            time.sleep(10)

    threading.Thread(target=scheduler_loop, daemon=True).start()

    from blog_monitor import start_blog_monitor
    start_blog_monitor()

    from interactive_bot import start_interactive_bot
    start_interactive_bot()


# ══════════════════════════════════════════════════════════════════════════════
# DATA PERSISTENCE
# ══════════════════════════════════════════════════════════════════════════════

def _save_analyses(new_analyses: list):
    os.makedirs("data", exist_ok=True)
    data = {"analyses": [], "stocks": [], "last_run": None}
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except:
            pass
    existing_urls = {a.get("url") for a in data.get("analyses", [])}
    new_unique = [a for a in new_analyses if a.get("url") not in existing_urls]
    data["analyses"] = data.get("analyses", []) + new_unique
    new_stocks = []
    for a in new_unique:
        new_stocks.extend(a.get("companies", []))
    existing_keys = {(s.get("name"), s.get("date_mentioned")) for s in data.get("stocks", [])}
    data["stocks"] = data.get("stocks", []) + [
        s for s in new_stocks if (s.get("name"), s.get("date_mentioned")) not in existing_keys
    ]
    data["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="🔱 titan_K v2")
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--blog", action="store_true")
    parser.add_argument("--macro", action="store_true")
    parser.add_argument("--listen", action="store_true")
    parser.add_argument("--schedule", action="store_true")
    parser.add_argument("--ping", action="store_true")
    parser.add_argument("--olympus", action="store_true")
    args = parser.parse_args()

    validate_config()

    if args.ping:
        from telegram_bot import send_test_ping
        send_test_ping()
    elif args.olympus:
        run_briefing("olympus", "Manual")
    elif args.test:
        run_briefing("morning_macro", "Test")
    elif args.blog:
        run_briefing("blog", "Manual")
    elif args.macro:
        run_briefing("morning_macro", "Manual")
    elif args.listen:
        _acquire_lock()
        from interactive_bot import start_interactive_bot
        start_interactive_bot()
    elif args.schedule:
        start_scheduler()
    else:
        start_full_system()


if __name__ == "__main__":
    main()

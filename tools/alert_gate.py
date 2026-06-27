"""tools/alert_gate.py — ONE place that decides whether Telegram is allowed to fire.

Two GOD directives are encoded here (Jun 27 2026):

1. WEEKENDS OFF. No autonomous Telegram on Saturday/Sunday. Markets are closed;
   the noise has zero decision value. Override with WEEKEND_ALERTS=on if ever needed.

2. NOISE IS GATED TO THE US SESSION. The always-on daemons (correlation engine,
   tech radar, intraday spike/drop scans) may only fire on weekdays inside the
   extended US window. Scheduled briefings have their own times and bypass this
   (they call ``scheduled_brief_allowed`` instead).

Berlin local time is the system clock everywhere, so we evaluate in Europe/Berlin.
US regular session ≈ 15:30–22:00 Berlin (summer). The extended noise window
13:30–23:30 covers pre-market through the post-close digest.
"""
from __future__ import annotations

import os
from datetime import datetime

try:
    import pytz
    _BERLIN = pytz.timezone("Europe/Berlin")
except Exception:  # pragma: no cover
    _BERLIN = None


def _env_on(key: str, default: bool) -> bool:
    v = os.getenv(key)
    if v is None or v.strip() == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def berlin_now() -> datetime:
    if _BERLIN is not None:
        return datetime.now(_BERLIN)
    return datetime.now()


def is_weekend(now: datetime | None = None) -> bool:
    now = now or berlin_now()
    return now.weekday() >= 5  # 5=Sat, 6=Sun


def weekend_muted(now: datetime | None = None) -> bool:
    """True when we must NOT send Telegram because it is the weekend.

    Default behaviour is muted on weekends. Set WEEKEND_ALERTS=on to allow.
    """
    if _env_on("WEEKEND_ALERTS", default=False):
        return False
    return is_weekend(now)


def _hour_float(now: datetime) -> float:
    return now.hour + now.minute / 60.0


def in_noise_window(now: datetime | None = None) -> bool:
    """Extended US session window for the always-on noise daemons (Berlin)."""
    now = now or berlin_now()
    start = float(os.getenv("NOISE_WINDOW_START_HOUR", "13.5"))
    end = float(os.getenv("NOISE_WINDOW_END_HOUR", "23.5"))
    return start <= _hour_float(now) <= end


def noise_allowed(now: datetime | None = None) -> bool:
    """Gate for correlation engine / tech radar / intraday scans.

    Weekday AND inside the extended US window. This is the single switch that
    silences the 24/7 'SECTOR WEAKNESS' style spam outside trading.
    """
    now = now or berlin_now()
    if is_weekend(now):
        return False
    return in_noise_window(now)


def scheduled_brief_allowed(now: datetime | None = None) -> bool:
    """Scheduled briefings: weekdays only (their times are set by the scheduler)."""
    return not is_weekend(now)


def suppress_reason(now: datetime | None = None) -> str | None:
    """Human-readable reason a send is suppressed, or None if allowed."""
    now = now or berlin_now()
    if weekend_muted(now):
        return "weekend_mute"
    return None

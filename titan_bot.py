#!/usr/bin/env python3
"""
TITAN LIQUIDITY BOT — OLYMPUS §11-PREDICT
==========================================
Automated Telegram briefing system for GOD
Runs on Contabo server (Ubuntu 24)

SCHEDULE:
  07:00  — Morning Liquidity Brief (MAIN)
  13:30  — US Market Open Alert
  16:30  — Midday Check
  19:00  — Market Close Summary
  23:30  — Asia Open Watch

WEDNESDAY 07:00 — Full 3-index recalculation

SETUP:
  1. pip install requests python-telegram-bot schedule --break-system-packages
  2. Set environment variables in config.py
  3. Run: python3 titan_bot.py
  4. Or install as systemd service (see README)
"""

import os
import json
import time
import logging
import schedule
import requests
from datetime import datetime, timezone
from config import (
    TELEGRAM_TOKEN,
    TELEGRAM_CHAT_ID,
    FRED_API_KEY,
)

# ── LOGGING ──
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('/var/log/titan_bot.log'),
        logging.StreamHandler()
    ]
)
log = logging.getLogger('TITAN')

# ── BERLIN TIME ──
def berlin_now():
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo('Europe/Berlin'))

def fmt_date():
    return berlin_now().strftime('%b %d, %Y')

def is_wednesday():
    return berlin_now().weekday() == 2


# ══════════════════════════════════════════════
# DATA FETCHERS
# ══════════════════════════════════════════════

def fetch_rrp() -> float:
    """Fetch latest Overnight Reverse Repo from FRED (RRPONTSYD)"""
    try:
        url = (
            f"https://api.stlouisfed.org/fred/series/observations"
            f"?series_id=RRPONTSYD"
            f"&api_key={FRED_API_KEY}"
            f"&file_type=json"
            f"&sort_order=desc"
            f"&limit=1"
        )
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        val = float(data['observations'][0]['value'])
        log.info(f"RRP fetched: ${val}B")
        return val
    except Exception as e:
        log.error(f"RRP fetch failed: {e}")
        return None


def fetch_reserves() -> float:
    """Fetch Reserve Balances from FRED (WRESBAL) — weekly, Wednesdays"""
    try:
        url = (
            f"https://api.stlouisfed.org/fred/series/observations"
            f"?series_id=WRESBAL"
            f"&api_key={FRED_API_KEY}"
            f"&file_type=json"
            f"&sort_order=desc"
            f"&limit=1"
        )
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        # WRESBAL is in Millions — convert to Billions
        val = float(data['observations'][0]['value']) / 1000
        log.info(f"Reserves fetched: ${val:.2f}B")
        return val
    except Exception as e:
        log.error(f"Reserves fetch failed: {e}")
        return None


def fetch_tga() -> float:
    """Fetch Treasury General Account from US Treasury Fiscal Data API"""
    try:
        url = (
            "https://api.fiscaldata.treasury.gov/services/api/v1/accounting/dts/dts_table_1"
            "?fields=record_date,open_today_bal,close_today_bal"
            "&filter=account_type:eq:Treasury General Account (TGA) Closing Balance"
            "&sort=-record_date"
            "&limit=1"
        )
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        val = float(data['data'][0]['close_today_bal']) / 1000  # millions → billions
        log.info(f"TGA fetched: ${val:.2f}B")
        return val
    except Exception as e:
        log.error(f"TGA fetch failed: {e}")
        # Fallback: try alternative endpoint
        try:
            url2 = (
                "https://api.fiscaldata.treasury.gov/services/api/v1/accounting/dts/dts_table_1"
                "?sort=-record_date&limit=5"
            )
            r2 = requests.get(url2, timeout=10)
            data2 = r2.json()
            for row in data2['data']:
                if 'Treasury General Account' in row.get('account_type', ''):
                    val = float(row['close_today_bal']) / 1000
                    log.info(f"TGA fetched (fallback): ${val:.2f}B")
                    return val
        except:
            pass
        return None


def fetch_fsi() -> dict:
    """
    Fetch OFR Financial Stress Index
    OFR provides data at: https://www.financialresearch.gov/financial-stress-index/
    Returns: { 'fsi': float, 'funding': float, 'safe_assets': float }
    """
    try:
        # OFR FSI API endpoint
        url = "https://www.financialresearch.gov/financial-stress-index/api/download?type=json"
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()

        # Get latest entry
        latest = data[-1] if isinstance(data, list) else data

        fsi_val  = float(latest.get('fsi', latest.get('FSI', 0)))
        funding  = float(latest.get('funding', latest.get('Funding', 0)))
        safe_ass = float(latest.get('safe_assets', latest.get('Safe Assets', 0)))

        log.info(f"FSI fetched: {fsi_val:.3f} | Funding: {funding:.3f} | Safe: {safe_ass:.3f}")
        return {'fsi': fsi_val, 'funding': funding, 'safe_assets': safe_ass}

    except Exception as e:
        log.error(f"FSI fetch failed: {e}")
        # Return last known good values if fetch fails
        return load_last_fsi()


def fetch_ranto28() -> str:
    """
    Fetch latest post title from ranto28 Naver blog RSS
    Returns post title if new post detected since last check
    """
    try:
        rss_url = "https://rss.blog.naver.com/ranto28.xml"
        headers = {'User-Agent': 'Mozilla/5.0 TITAN/1.0'}
        r = requests.get(rss_url, timeout=10, headers=headers)
        r.raise_for_status()

        # Simple XML title extraction without lxml
        content = r.text
        import re
        titles = re.findall(r'<title><!\[CDATA\[(.*?)\]\]></title>', content)
        if len(titles) > 1:
            latest_title = titles[1]  # Skip feed title, get first post
            log.info(f"ranto28 latest: {latest_title}")

            # Check if new (compare to cached)
            last_title = load_cache('ranto28_last_title')
            if last_title != latest_title:
                save_cache('ranto28_last_title', latest_title)
                return f"📰 NEW POST: {latest_title}"
        return None
    except Exception as e:
        log.warning(f"ranto28 fetch failed: {e}")
        return None


# ══════════════════════════════════════════════
# CACHE / PERSISTENCE
# ══════════════════════════════════════════════

CACHE_FILE = '/home/titan/titan_cache.json'

def load_cache(key, default=None):
    try:
        with open(CACHE_FILE, 'r') as f:
            return json.load(f).get(key, default)
    except:
        return default

def save_cache(key, value):
    try:
        cache = {}
        try:
            with open(CACHE_FILE, 'r') as f:
                cache = json.load(f)
        except:
            pass
        cache[key] = value
        with open(CACHE_FILE, 'w') as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        log.error(f"Cache save failed: {e}")

def load_last_fsi():
    return load_cache('last_fsi', {'fsi': -0.568, 'funding': -0.42, 'safe_assets': -0.31})

def save_last_fsi(fsi_data):
    save_cache('last_fsi', fsi_data)


# ══════════════════════════════════════════════
# LIQUIDITY ENGINE — 4-LAYER SIGNAL LOGIC
# ══════════════════════════════════════════════

def calculate_net_liquidity(rrp, reserves, tga) -> float:
    return reserves - tga - rrp


def layer1_signal(net_liq: float) -> dict:
    """Layer 1: Current Liquidity State"""
    if net_liq > 2500:
        return {
            'code':    'DEPLOY',
            'emoji':   '🟢',
            'label':   'MAX DEPLOY',
            'detail':  'Net Liq > $2,500B. Full deployment. GOD Score 80+.',
            'min_score': 80,
        }
    elif net_liq > 2200:
        return {
            'code':    'SELECTIVE',
            'emoji':   '🟡',
            'label':   'SELECTIVE DEPLOY',
            'detail':  'Net Liq $2,200-2,500B. GOD Score 85+ only. Keep 30% reserve.',
            'min_score': 85,
        }
    elif net_liq > 1900:
        return {
            'code':    'HOLD',
            'emoji':   '🟠',
            'label':   'HOLD — PROTECT',
            'detail':  'Net Liq $1,900-2,200B. Only GOD Score 87+ on confirmed dips.',
            'min_score': 87,
        }
    else:
        return {
            'code':    'CASH',
            'emoji':   '🔴',
            'label':   'MAXIMUM CASH',
            'detail':  'Net Liq < $1,900B. Critical. Exit speculative positions.',
            'min_score': None,
        }


def layer2_next_events() -> list:
    """Layer 2: 60-Day Forward Calendar — next 3 events"""
    now = berlin_now()
    events = [
        {'date': datetime(now.year, 4,  6,  tzinfo=now.tzinfo), 'name': 'Iran Deadline',    'type': '⚔️ BINARY',  'action': 'Watch. Ceasefire=buy, no deal=protect'},
        {'date': datetime(now.year, 4, 15,  tzinfo=now.tzinfo), 'name': 'US Tax Day',        'type': '🔴 DRAIN',   'action': 'Reduce exposure by Apr 10'},
        {'date': datetime(now.year, 4, 15,  tzinfo=now.tzinfo), 'name': 'ASML Earnings',     'type': '🟢 CATALYST','action': 'Buy before — limit €1,100 armed'},
        {'date': datetime(now.year, 4, 30,  tzinfo=now.tzinfo), 'name': 'FOMC Meeting',      'type': '🔵 FED',     'action': 'Watch rate decision'},
        {'date': datetime(now.year, 5, 13,  tzinfo=now.tzinfo), 'name': 'RKLB Earnings',     'type': '🚀 PORT',    'action': 'Neutron update expected'},
        {'date': datetime(now.year, 6, 15,  tzinfo=now.tzinfo), 'name': 'Q2 Tax Drain',      'type': '🟡 DRAIN',   'action': 'Mild tightening expected'},
    ]
    upcoming = []
    for ev in events:
        days = (ev['date'].date() - now.date()).days
        if 0 <= days <= 90:
            ev['days'] = days
            upcoming.append(ev)
    # Sort by days, return next 3
    upcoming.sort(key=lambda x: x['days'])
    return upcoming[:3]


def layer3_fsi_check(fsi_data: dict) -> dict:
    """Layer 3: FSI Ejection Seat"""
    fsi     = fsi_data.get('fsi', 0)
    funding = fsi_data.get('funding', 0)
    safe_a  = fsi_data.get('safe_assets', 0)

    if fsi > 1.0 or funding > 0.5 or safe_a > 0.5:
        return {
            'level':    'CRITICAL',
            'emoji':    '🚨',
            'override': True,
            'action':   'EJECT — MAXIMUM CASH IMMEDIATELY',
            'detail':   'FSI critical. All logic overridden. Protect capital.',
        }
    elif fsi > 0.0 or funding > 0.0 or safe_a > 0.0:
        return {
            'level':    'ABORT',
            'emoji':    '⛔',
            'override': True,
            'action':   'ABORT ALL BUYS — FSI CROSSED ZERO',
            'detail':   'No new positions. Raise stop-losses. Wait for FSI < -0.2.',
        }
    elif fsi > -0.3 or funding > -0.2 or safe_a > -0.2:
        return {
            'level':    'WATCH',
            'emoji':    '👁️',
            'override': False,
            'action':   'WATCH — STRESS APPROACHING ZERO',
            'detail':   'Reduce to 70% invested. No new speculative positions.',
        }
    else:
        return {
            'level':    'SAFE',
            'emoji':    '✅',
            'override': False,
            'action':   'SAFE — PROCEED WITH LIQUIDITY LOGIC',
            'detail':   'FSI normal. Sub-indices clear. Normal deployment logic applies.',
        }


def layer4_early_warning(fsi_data: dict) -> dict:
    """Layer 4: Early Warning — velocity and convergence check"""
    fsi     = fsi_data.get('fsi', 0)
    funding = fsi_data.get('funding', 0)
    safe_a  = fsi_data.get('safe_assets', 0)

    # Load prior FSI for velocity check
    prior   = load_last_fsi()
    vel     = fsi - prior.get('fsi', fsi)

    warnings = []
    if vel > 0.15:
        warnings.append(f"FSI velocity +{vel:.3f} in 5d — acceleration detected")
    if funding > -0.2:
        warnings.append(f"Funding index at {funding:.3f} — approaching zero")
    if safe_a > -0.2:
        warnings.append(f"Safe assets at {safe_a:.3f} — approaching zero")
    if vel > 0.05 and fsi > -0.4:
        warnings.append("Convergence risk: rising FSI + near zero level")

    if warnings:
        return {
            'level':    'WARNING',
            'emoji':    '⚠️',
            'messages': warnings,
            'action':   'Reduce to 70% invested. Tighten stops on GOD Score < 75.',
        }
    else:
        return {
            'level':    'CLEAR',
            'emoji':    '🛡️',
            'messages': [],
            'action':   'No pre-crash signals. All clear.',
        }


# ══════════════════════════════════════════════
# MESSAGE BUILDERS
# ══════════════════════════════════════════════

def build_morning_message(rrp, reserves, tga, fsi_data, ranto_alert=None) -> str:
    """Build the full 07:00 morning liquidity brief"""
    net   = calculate_net_liquidity(rrp, reserves, tga)
    l1    = layer1_signal(net)
    l3    = layer3_fsi_check(fsi_data)
    l4    = layer4_early_warning(fsi_data)
    evts  = layer2_next_events()
    fsi   = fsi_data.get('fsi', 0)
    fund  = fsi_data.get('funding', 0)
    safe  = fsi_data.get('safe_assets', 0)

    # Final command — FSI overrides Layer 1
    if l3['override']:
        final_cmd   = l3['action']
        final_emoji = l3['emoji']
    else:
        final_cmd   = l1['label']
        final_emoji = l1['emoji']

    wed_tag = " · 📅 WEDNESDAY FULL RECALC" if is_wednesday() else ""

    lines = [
        f"🔱 *OLYMPUS §11-PREDICT*",
        f"07:00 Daily Brief · {fmt_date()}{wed_tag}",
        f"",
        f"━━━ ⚡ COMMAND ━━━",
        f"{final_emoji} *{final_cmd}*",
        f"",
    ]

    # Layer 4 early warning — show if not clear
    if l4['level'] == 'WARNING':
        lines += [
            f"⚠️ *EARLY WARNING ACTIVE*",
        ]
        for w in l4['messages']:
            lines.append(f"  → {w}")
        lines.append(f"  Action: {l4['action']}")
        lines.append("")

    # Layer 1 detail
    lines += [
        f"━━━ 📊 LAYER 1 — NET LIQUIDITY ━━━",
        f"Net Liq: *${net:.0f}B*",
        f"RRP  (역레포):  ${rrp:.3f}B  ✅",
        f"RES  (지준금):  ${reserves:.0f}B  {'📉' if reserves < 3000 else '➡'}",
        f"TGA  (국고계좌): ${tga:.0f}B  {'⚠️' if tga > 700 else '✅'}",
        f"Signal: {l1['emoji']} {l1['label']}",
        f"Min GOD Score: {l1['min_score'] or 'N/A — protect capital'}",
        f"",
    ]

    # Layer 3 FSI
    fsi_icon = '✅' if fsi < 0 else ('🚨' if fsi > 0 else '⚠️')
    fund_icon = '✅' if fund < 0 else '🚨'
    safe_icon = '✅' if safe < 0 else '🚨'
    lines += [
        f"━━━ 🔦 LAYER 3 — FSI STRESS ━━━",
        f"FSI:     {fsi:.3f}  {fsi_icon}",
        f"Funding: {fund:.3f}  {fund_icon}",
        f"Safe A:  {safe:.3f}  {safe_icon}",
        f"Status: {l3['emoji']} {l3['action'][:50]}",
        f"",
    ]

    # Layer 2 calendar
    if evts:
        lines.append("━━━ 📅 LAYER 2 — NEXT EVENTS ━━━")
        for ev in evts:
            warn_flag = " ← ACT NOW" if ev['days'] <= 7 else ""
            lines.append(f"{ev['type']} {ev['name']} — {ev['days']}d{warn_flag}")
            lines.append(f"  → {ev['action']}")
        lines.append("")

    # ranto28 alert
    if ranto_alert:
        lines += [
            f"━━━ 📰 RANTO28 NEW POST ━━━",
            f"{ranto_alert}",
            f"",
        ]

    lines += [
        f"━━━ 🏝️ ISLAND MISSION ━━━",
        f"Target: 47% CAGR · 2036",
        f"Wed = full 3-index recalculation",
        f"MINERVA · TITAN · OLYMPUS 🔱",
    ]

    return "\n".join(lines)


def build_market_open_message() -> str:
    """13:30 — US Market Open alert"""
    return (
        f"🔱 *OLYMPUS — 13:30 US OPEN*\n"
        f"{fmt_date()}\n\n"
        f"US markets now open.\n"
        f"Check: VIX · Oil · S\\&P futures vs open\n"
        f"Active limit orders: ASML €1,100 · RKLB €58\n"
        f"NTR ex-date status: {'✅ PAST' if berlin_now().month >= 4 else '⏳ Mar 31'}\n\n"
        f"MINERVA · TITAN 🔱"
    )


def build_midday_message() -> str:
    """16:30 — Midday check"""
    return (
        f"🔱 *OLYMPUS — 16:30 MIDDAY*\n"
        f"{fmt_date()}\n\n"
        f"Midday check: Iran headlines · Sector rotation\n"
        f"Watch: PLTR · TSMC · RKLB intraday\n"
        f"Any limit order fills? Check TR app.\n\n"
        f"MINERVA · TITAN 🔱"
    )


def build_close_message() -> str:
    """19:00 — Market close summary"""
    return (
        f"🔱 *OLYMPUS — 19:00 CLOSE*\n"
        f"{fmt_date()}\n\n"
        f"US markets closed.\n"
        f"Review: Portfolio P\\&L · Any GOD Score changes?\n"
        f"Tomorrow's setup: Iran overnight · Asian futures\n"
        f"Next liquidity update: 07:00 tomorrow\n\n"
        f"MINERVA · TITAN · ISLAND 🔱"
    )


def build_asia_message() -> str:
    """23:30 — Asia open watch"""
    ranto = fetch_ranto28()
    lines = [
        f"🔱 *OLYMPUS — 23:30 ASIA OPEN*",
        f"{fmt_date()}",
        f"",
        f"Asia markets opening.",
        f"Watch: Nikkei · Hang Seng · Xiaomi (HK)",
        f"Overnight: Iran news · S\\&P futures",
        f"",
    ]
    if ranto:
        lines += [f"📰 *ranto28*: {ranto}", ""]
    lines.append("MINERVA · TITAN 🔱")
    return "\n".join(lines)


# ══════════════════════════════════════════════
# TELEGRAM SENDER
# ══════════════════════════════════════════════

def send_telegram(message: str) -> bool:
    """Send message to GOD's Telegram chat"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        'chat_id':    TELEGRAM_CHAT_ID,
        'text':       message,
        'parse_mode': 'Markdown',
    }
    try:
        r = requests.post(url, json=payload, timeout=15)
        r.raise_for_status()
        log.info("Telegram message sent ✅")
        return True
    except Exception as e:
        log.error(f"Telegram send failed: {e}")
        return False


# ══════════════════════════════════════════════
# SCHEDULED JOBS
# ══════════════════════════════════════════════

def job_morning():
    """07:00 — Main liquidity brief"""
    log.info("=== 07:00 MORNING JOB STARTING ===")
    try:
        # Fetch all data
        rrp      = fetch_rrp()
        tga      = fetch_tga()
        reserves = fetch_reserves() if is_wednesday() else load_cache('last_reserves', 2993.955)
        fsi_data = fetch_fsi()
        ranto    = fetch_ranto28()

        # Use cached if fetch failed
        if rrp      is None: rrp      = load_cache('last_rrp',      2.844)
        if tga      is None: tga      = load_cache('last_tga',      870.86)
        if reserves is None: reserves = load_cache('last_reserves', 2993.955)

        # Cache successfully fetched values
        if rrp:      save_cache('last_rrp',      rrp)
        if tga:      save_cache('last_tga',      tga)
        if reserves: save_cache('last_reserves', reserves)
        if fsi_data: save_last_fsi(fsi_data)

        # Build and send
        msg = build_morning_message(rrp, reserves, tga, fsi_data, ranto)
        send_telegram(msg)

    except Exception as e:
        log.error(f"Morning job error: {e}")
        send_telegram(f"⚠️ TITAN: Morning brief error — {e}\nCheck logs.")


def job_open():
    """13:30 — US Market Open"""
    log.info("=== 13:30 MARKET OPEN JOB ===")
    send_telegram(build_market_open_message())


def job_midday():
    """16:30 — Midday"""
    log.info("=== 16:30 MIDDAY JOB ===")
    send_telegram(build_midday_message())


def job_close():
    """19:00 — Market Close"""
    log.info("=== 19:00 CLOSE JOB ===")
    send_telegram(build_close_message())


def job_asia():
    """23:30 — Asia Open"""
    log.info("=== 23:30 ASIA JOB ===")
    send_telegram(build_asia_message())


# ══════════════════════════════════════════════
# SCHEDULER SETUP
# ══════════════════════════════════════════════

def setup_schedule():
    """All times are Berlin/CET/CEST"""
    schedule.every().day.at("07:00").do(job_morning)
    schedule.every().day.at("13:30").do(job_open)
    schedule.every().day.at("16:30").do(job_midday)
    schedule.every().day.at("19:00").do(job_close)
    schedule.every().day.at("23:30").do(job_asia)
    log.info("Schedule armed: 07:00 / 13:30 / 16:30 / 19:00 / 23:30")


# ══════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════

if __name__ == '__main__':
    log.info("🔱 TITAN LIQUIDITY BOT STARTING")
    log.info("OLYMPUS §11-PREDICT · ISLAND MISSION 2036")
    setup_schedule()

    # Send startup confirmation
    send_telegram(
        "🔱 *TITAN BOT ONLINE*\n"
        f"Started: {fmt_date()} {berlin_now().strftime('%H:%M')}\n"
        "Schedule: 07:00 · 13:30 · 16:30 · 19:00 · 23:30\n"
        "Liquidity Engine: ACTIVE\n"
        "FSI Monitor: ACTIVE\n"
        "ranto28 Watch: ACTIVE\n\n"
        "MINERVA · OLYMPUS §11 · ISLAND 🏝️"
    )

    # Run loop
    while True:
        schedule.run_pending()
        time.sleep(30)

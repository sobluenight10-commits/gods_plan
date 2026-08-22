#!/usr/bin/env python3
"""OLYMPUS Sunday Prep — 주말 운영원칙 (GOD directive 2026-08-22):
주말은 정보 소비가 아니라 '결정 압축' 시간. 서버가 템플릿의 3/4를 자동 생성.
기본 정답은 'no action — limits armed'. 행동은 예외일 때만."""
import json, os, datetime, urllib.request

BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

def _load(p, d):
    try: return json.load(open(p))
    except Exception: return d

sc = _load(os.path.join(BASE, "scores.json"), {})
dr = _load(os.path.join(BASE, "directives.json"), {})
try:
    hb = json.load(open("/var/www/html/heartbeat.json"))
except Exception:
    hb = {}

now = datetime.datetime.now(datetime.timezone.utc)
liq = dr.get("liquidity") or {}
zone = (sc.get("gate") or {}).get("zone", "?")
mult = (sc.get("gate") or {}).get("mult", "?")

lines = ["📋 <b>OLYMPUS 일요일 40분 프렙</b> — 서버 자동생성분 (읽고 1문장만 완성할 것)", ""]
lines.append(f"① 게이트: <b>{zone}</b> (×{mult}) · 순유동성 ${liq.get('liquidity_usd_bn','?')}B · {liq.get('corridor_status','?')} corridor")

held = [r for r in sc.get("scores", []) if r.get("held")]
lines.append("")
lines.append("② 보유 종목 괴리/액션 (zone-distance):")
for r in sorted(held, key=lambda x: -(x.get("god") or 0))[:8]:
    lines.append(f"  · {r['t']} GOD {r['god']} {r['action']} · 20W괴리 {r.get('dist')}% · 언급 {r.get('sent',0):+.0f}")

lines.append("")
lines.append("③ 다음 주 확정 이벤트: 8/26 NVDA 실적 → 8/28 잭슨홀(워시, 23시) → 9/16 FOMC")
stale = []
for job, ts in hb.items():
    try:
        t = datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if (now - t).total_seconds() > 26 * 3600: stale.append(job)
    except Exception: pass
lines.append(f"④ 유지보수: {'⚠ stale: ' + ', '.join(stale) if stale else '전 잡 정상'}")

lines.append("")
lines.append("⑤ 이번 주 ONE COMMAND (기본값):")
if zone == "CLOSED":
    lines.append("   → <b>no action — 게이트 닫힘, 현금 방어</b>")
else:
    acts = ["%s %s" % (r['t'], r['action']) for r in held if r.get("action") in ("ACCUMULATE","BUY ON DIP","TRIM")][:4]
    lines.append("   → " + (" · ".join(acts) if acts else "<b>no action — limits armed</b>"))
lines.append("")
lines.append("<i>원칙: 주말 10시간 분석은 위성 슬리브 손실의 재현. 40분으로 압축. "
             "€ 목표는 북극성이지 캘린더 입력값이 아님 — 자본기여가 수익률을 지배하는 구간.</i>")

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from telegram_bot import send_telegram
send_telegram("\n".join(lines))
print("sunday prep sent")

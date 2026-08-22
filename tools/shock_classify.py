#!/usr/bin/env python3
"""shock_classify.py — 쇼크 원인 5분류기
shock_events.json 미분류 건을 ①논제파괴 ②실적·가이던스 ③거시·금리 ④심리·과잉 ⑤기술적으로 분류,
충격강도 자동 부여 → thesis_check.py 의 R 산정에 자동 주입 (shock_class.json)."""
import json, os, re, datetime

DATA = "/root/gods_plan/data"
ev_path = os.path.join(DATA, "shock_events.json")
events = json.load(open(ev_path)) if os.path.exists(ev_path) else []
if not events:
    print("no events"); raise SystemExit

# 뉴스 코퍼스: full_feed_v2.jsonl + topics.json
texts = {}
fp = os.path.join(DATA, "full_feed_v2.jsonl")
if os.path.exists(fp):
    for line in open(fp):
        try:
            d = json.loads(line)
            t = d.get("t") or d.get("ticker")
            if t: texts.setdefault(t, []).append(((d.get("title") or "") + " " + (d.get("body") or d.get("summary") or "")).lower())
        except Exception: pass

CAT = [
    ("논제파괴", 0.8, r"기술대체|내재화|obsolete|disrupt|replace|점유율.*침탈|lost.*share|patent.*invalid|핵심기술"),
    ("실적·가이던스", 0.6, r"guidance|가이던스|실적|earnings|miss|하향|downgrade|목표가.*하향|매출.*부진|profit warn"),
    ("거시·금리", 0.35, r"금리|fomc|연준|fed|rate hike|inflation|cpi|고용|경기침체|recession|워시|warsh|잭슨홀"),
    ("심리·과잉", 0.2, r"공포|패닉|panic|과열|버블|bubble|short report|공매도|루머|rumor"),
]
SEV_DEFAULT = ("기술적", 0.15)  # 수급·만기 등 설명 불가

res = {}
for e in events:
    if e.get("cls"): continue
    t = e["t"]
    blob = " ".join(texts.get(t, [])[-30:])
    # SEC 8-K가 3일 내 있으면 최소 '실적·가이던스'급 사실 이벤트
    best, score = None, 0
    for name, sev, pat in CAT:
        n = len(re.findall(pat, blob))
        if n > score: best, score = (name, sev), n
    if best is None:
        best = ("실적·가이던스", 0.6) if e.get("sec_8k") else SEV_DEFAULT
    e["cls"] = best[0]; e["sev"] = best[1]; e["evidence_hits"] = score
    res.setdefault(t, []).append({"date": e["date"], "ret_pct": e["ret_pct"], "cls": best[0], "sev": best[1]})

json.dump(events, open(ev_path, "w"), ensure_ascii=False, indent=1)
out = {"updated": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
       "categories": {"논제파괴": 0.8, "실적·가이던스": 0.6, "거시·금리": 0.35, "심리·과잉": 0.2, "기술적": 0.15},
       "by_ticker": res}
json.dump(out, open(os.path.join(DATA, "shock_class.json"), "w"), ensure_ascii=False, indent=1)
print("classified", sum(len(v) for v in res.values()), "건")
for t, v in res.items():
    for x in v: print(t, x["date"], f"{x['ret_pct']:+.1f}%", "→", x["cls"], f"(강도 {x['sev']})")

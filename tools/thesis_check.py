#!/usr/bin/env python3
"""thesis_check.py — TDR(논제 파괴도 비율) 엔진
R = Σ 세그먼트비중×충격강도  (충격강도 키워드: 소송0.1 규제0.3 실적미스0.4 고객이탈0.6 기술대체0.8)
P = 실제 20일 낙폭%   →   TDR = |P| / max(R·100, 1)
≥2.5 과잉반응(눌림 후보) / 1~2.5 정당 / <1 과소반응(위험) / 부정 이벤트 없으면 논제 무사."""
import json, warnings, os
warnings.filterwarnings("ignore")
_p = "/root/gods_plan/data/shock_class.json"
SHOCK = json.load(open(_p)).get("by_ticker", {}) if os.path.exists(_p) else {}
TM = json.load(open("/root/gods_plan/data/thesis_map.json"))
T = json.load(open("/root/gods_plan/data/ranto28/topics.json"))
VS = json.load(open("/root/gods_plan/data/value_sakata.json"))["tickers"]
OVR = json.load(open("/var/www/html/data/holdings_override.json"))
HELD = [k for k, v in OVR.items() if isinstance(v, dict) and v.get("held")]

SEV = [("기술대체|대체|내재화|자체설계|독점 붕괴", 0.8),
       ("고객이탈|계약 상실|탈락|무산|취소", 0.6),
       ("실적미스|어닝미스|가이던스 하향|적자", 0.4),
       ("규제|제재|관세 부과|금지", 0.3),
       ("소송|집단소송|리콜|조사|경고", 0.1),
       ("하락|급락|폭락|약세|우려", 0.15)]
import re
def severity(txt):
    for pat, s in SEV:
        if re.search(pat, txt): return s
    return 0.1

def seg_hit(tk, txt):
    """텍스트가 건드리는 세그먼트 비중 합산. 못 찾으면 0.3(회사 전반) 가정."""
    segs = TM.get(tk, {}).get("segs", {})
    hit = 0.0
    for seg, w in segs.items():
        keys = re.split(r"[/()·]", seg)
        if any(k and k in txt for k in keys): hit += w
    return hit if hit else 0.3

out = {}
for tk in HELD:
    tinfo = next((x for x in T["tickers"] if x["t"] == tk), {})
    negs = [c for c in tinfo.get("contrib", []) if c.get("c", 0) <= -1.5 and (c.get("date") or "") >= "2026-06-01"]
    d20 = (VS.get(tk) or {}).get("d20")
    if not negs:
        out[tk] = {"status": "논제 무사 — 부정 이벤트 없음", "tdr": None, "P": d20, "R": None,
                   "thesis": TM.get(tk, {}).get("thesis", ""), "kill": TM.get(tk, {}).get("kill", "")}
        continue
    R = max(seg_hit(tk, c["title"]) * severity(c["title"]) for c in negs) * 100
    sh = SHOCK.get(tk, [])
    if sh:
        R = max(R, max(s["sev"] for s in sh) * 0.3 * 100)  # 분류된 쇼크 강도 × 회사전반 0.3 → R 자동 주입
    P = abs(d20) if d20 is not None and d20 < 0 else None
    tdr = round(P / max(R, 1), 1) if P else None
    if tdr is None:
        verdict = "부정 이벤트 있으나 주가 미반응 — 추적"
    elif tdr >= 3.0: verdict = "극심한 과잉반응 — 적극 눌림매수 (패닉이 사실을 압도)"
    elif tdr >= 2.0: verdict = "과잉반응 — 눌림매수 후보 (심리만 패닉)"
    elif tdr >= 1.5: verdict = "경미한 과잉반응 — 관망, 조건부 리밋 무장"
    elif tdr >= 1.0: verdict = "정당한 반응 — 관망"
    elif tdr >= 0.7: verdict = "경미한 과소반응 — 경계 강화"
    elif tdr >= 0.4: verdict = "⚠ 과소반응 — 피해 미반영, 비중축소 검토"
    else:            verdict = "⛔ 심각한 과소반응 — 논제 킬 기준 재심사"
    out[tk] = {"status": verdict, "tdr": tdr, "P": d20, "R": round(R, 1),
               "worst": max(negs, key=lambda c: -c["c"])["title"][:60],
               "thesis": TM.get(tk, {}).get("thesis", ""), "kill": TM.get(tk, {}).get("kill", "")}
json.dump({"formula": "TDR = |20일낙폭%| / max(Σ 세그먼트비중×충격강도 ×100, 1) · ≥3.0 극심한과잉(적극매수) / 2.0~3.0 과잉(눌림후보) / 1.5~2.0 경미과잉(조건부리밋) / 1.0~1.5 정당(관망) / 0.7~1.0 경미과소(경계) / 0.4~0.7 과소(축소검토) / <0.4 심각과소(킬기준 재심사)",
           "tickers": out}, open("/root/gods_plan/data/thesis_status.json", "w"), ensure_ascii=False, indent=1)
flag = {k: v for k, v in out.items() if v["tdr"] is not None}
print("TDR 계산:", len(flag), "건")
for k, v in sorted(flag.items(), key=lambda x: -x[1]["tdr"]): print(k, "TDR", v["tdr"], "·", v["status"][:30], "·", v["worst"][:30])

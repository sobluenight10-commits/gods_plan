#!/usr/bin/env python3
# liq_forward.py — 포워드 순유동성 프로젝션 (시나리오 3종, 확률·출처 태그)
# 원칙: 모든 수치는 [추정]이며 확률은 모델 판단. 출처만 검증된 사실(FRED H.4.1, QRA)에 태그.
import json, datetime, os

HIST="/root/gods_plan/data/liquidity_history.json"
OUT="/root/gods_plan/data/liq_forward.json"
SNAP=json.load(open(HIST))["snapshots"]
last=SNAP[-1]
cur=last["net_liq"]; d0=datetime.date.fromisoformat(last["date"])
tga=last.get("tga_b") or 0.0; rrp=last.get("rrp_b") or 0.0

# 구조적 사실: RRP 잔고 ~0 → 완충 소진, 러노프는 준비금·순유동성을 직접 감소시킴
# 월간 드리프트($B/월) — [추정]: MBS 러노프 캡 기준 + TGA 경로
SCEN=[
 dict(key="base", label="기준: 완만한 러노프 지속", prob=0.55, drift=-20,
      why="MBS 캡 $35B 중 실질 러노프 ~$20B 가정, TGA 현 수준 유지",
      src=["FRED H.4.1 (WALCL 주간)", "Fed 러노프 캡 공표"]),
 dict(key="hawk", label="매파: Warsh식 대차대조표 축소 가속", prob=0.25, drift=-45,
      why="러노프 $40B+/월 + TGA 재충전 시 준비금 직격. 잭슨홀(8/28)·QRA(11/4)가 분기점",
      src=["Fed Warsh 의장 발언 기조 [검증 필요]", "QRA 차입계획(분기)"]),
 dict(key="dove", label="완화: 러노프 종료·단기재정증권 편중 발행", prob=0.20, drift=+15,
      why="QT 종료 선언 + 빌 편중 발행 시 순유동성 순증. 금리인하 사이클 동반 시 상승폭 확대",
      src=["FRED H.4.1", "QRA 발행 구성"]),
]
# 확률 정규화 (합=1)
s=sum(x["prob"] for x in SCEN)
for x in SCEN: x["prob"]=round(x["prob"]/s,2)

months=[]
for m in range(1,13):
    # 다음 달 같은 일자 근사
    mo=d0.month+m-1; yr=d0.year+mo//12; mo=mo%12+1
    day=min(d0.day,28)
    months.append(f"{yr:04d}-{mo:02d}-{day:02d}")

fwd={"generated":datetime.datetime.utcnow().isoformat(timespec="seconds")+"Z",
     "anchor":{"date":last["date"],"net_liq":cur,"tga_b":tga,"rrp_b":rrp},
     "note":"모든 포워드 수치는 [추정] — 확률은 모델 판단이며 사실이 아님. 출처 태그는 시나리오 근거의 출처.",
     "structural":"RRP 잔고 ~0으로 완충 소진 — 러노프는 이제 준비금/순유동성을 1:1로 감소시킴 [FRED H.4.1]",
     "scenarios":[]}
for x in SCEN:
    pts=[{"date":months[i],"net_liq":round(cur+x["drift"]*(i+1),1)} for i in range(12)]
    fwd["scenarios"].append({**x,"points":pts})
json.dump(fwd,open(OUT,"w"),ensure_ascii=False,indent=1)
print("liq_forward:",last["date"],cur,"->",[ (x['key'],x['prob'],x['points'][-1]['net_liq']) for x in fwd['scenarios']])

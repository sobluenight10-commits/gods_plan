import json
BASE="/root/gods_plan"
d=json.load(open(BASE+"/data/blog_tickers.json",encoding="utf-8"))
ts=d.get("tickers") or []
print("== sample blog tickers (first 8) ==")
for x in ts[:8]:
    print("  ",json.dumps(x,ensure_ascii=False)[:200])
print("== keys present across tickers ==")
keys=set()
for x in ts:
    if isinstance(x,dict): keys|=set(x.keys())
print("  ",sorted(keys))
g=json.load(open(BASE+"/data/knowledge_graph.json",encoding="utf-8"))
n=g.get("nodes") or []
print("== node sample fields ==")
for x in n[:4]:
    print("  ",json.dumps(x,ensure_ascii=False)[:200])
print("== node keys ==", sorted({k for x in n for k in x.keys()}))
# any node that looks like a ticker?
print("== top 15 nodes by degree ==")
for x in sorted(n,key=lambda z:z.get("degree",0) or 0,reverse=True)[:15]:
    print("  ",x.get("id"),"| label:",x.get("label"),"| type:",x.get("type"),"| deg:",x.get("degree"))

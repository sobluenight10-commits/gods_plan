import json
with open('/root/gods_plan/data/directives.json', encoding='utf-8') as f:
    d = json.load(f)
print('keys', list(d.keys())[:30])
gs = d.get('god_scores')
print('god_scores', type(gs).__name__, len(gs) if isinstance(gs, list) else gs)

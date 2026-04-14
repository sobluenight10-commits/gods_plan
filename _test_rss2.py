import requests, re, datetime
from email.utils import parsedate_to_datetime
from datetime import timezone

now = datetime.datetime.now(timezone.utc)
cutoff = now - datetime.timedelta(hours=48)
print(f"NOW (UTC): {now}")
print(f"CUTOFF (48h ago): {cutoff}\n")

r = requests.get("https://rss.blog.naver.com/ranto28.xml", timeout=15, headers={"User-Agent": "Mozilla/5.0"})
items = re.findall(r"<item>(.*?)</item>", r.text, re.DOTALL)

for i, item in enumerate(items[:15]):
    title_m = re.search(r"<title><!\[CDATA\[(.*?)\]\]></title>", item)
    date_m = re.search(r"<pubDate>(.*?)</pubDate>", item)
    title = title_m.group(1).strip() if title_m else "?"
    raw_date = date_m.group(1).strip() if date_m else "?"
    
    try:
        pd = parsedate_to_datetime(raw_date)
    except:
        pd = None
    
    within = "YES" if pd and pd >= cutoff else "NO"
    delta = f" ({(now-pd).total_seconds()/3600:.1f}h ago)" if pd else ""
    print(f"#{i+1} [{within}]{delta}")
    print(f"   raw: {raw_date}")
    print(f"   parsed: {pd}")
    print(f"   title: {title[:70]}")
    print()

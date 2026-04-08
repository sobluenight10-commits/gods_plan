# TITAN LIQUIDITY BOT — CONTABO SETUP GUIDE
## OLYMPUS §11-PREDICT · Island Mission 2036

---

## STEP 1 — Fix Contabo SSH (if needed)
```bash
# If SSH port 22 is blocked, use Contabo VNC console:
# → my.contabo.com → Server → VNC Console

# Check if SSH is running
systemctl status ssh

# If not running
systemctl start ssh
systemctl enable ssh

# Check firewall
ufw status
ufw allow 22
```

---

## STEP 2 — Create Telegram Bot

1. Open Telegram → search **@BotFather**
2. Send: `/newbot`
3. Name: `TITAN OLYMPUS`
4. Username: `titan_olympus_bot` (must be unique)
5. **Copy the API token** → paste in `config.py`

Get your Chat ID:
```
https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
```
Send any message to the bot first, then open that URL.
Find: `"chat":{"id": 123456789}` → copy that number.

---

## STEP 3 — Get FRED API Key (free)

1. Go to: https://fredaccount.stlouisfed.org/login/secure/
2. Register free account
3. My Account → API Keys → Request API Key
4. Copy key → paste in `config.py`

---

## STEP 4 — Upload Files to Contabo

```bash
# From your local machine
scp -r titan_bot/ root@5.189.176.185:/home/titan/

# Or create on server directly
ssh root@5.189.176.185
mkdir -p /home/titan/titan_bot
```

---

## STEP 5 — Install Dependencies

```bash
pip install requests schedule python-telegram-bot --break-system-packages

# Verify python3 available
python3 --version

# Test run (manual)
cd /home/titan/titan_bot
python3 titan_bot.py
```

---

## STEP 6 — Install as Systemd Service (runs forever)

```bash
# Copy service file
cp titan_bot.service /etc/systemd/system/

# Enable and start
systemctl daemon-reload
systemctl enable titan_bot
systemctl start titan_bot

# Check status
systemctl status titan_bot

# View live logs
journalctl -u titan_bot -f
```

---

## STEP 7 — Test Each Alarm Manually

```python
# In Python console on server
import sys
sys.path.insert(0, '/home/titan/titan_bot')
from titan_bot import *

# Test morning brief
job_morning()

# Test telegram send
send_telegram("🔱 TITAN TEST — System Online")
```

---

## TROUBLESHOOTING

**Bot not sending?**
- Check TELEGRAM_TOKEN and TELEGRAM_CHAT_ID in config.py
- Test: `curl https://api.telegram.org/bot<TOKEN>/getMe`

**FRED API failing?**
- Verify API key at: https://fred.stlouisfed.org/docs/api/api_key.html
- Bot uses cached values as fallback — will not crash

**TGA fetch failing?**
- Treasury API sometimes changes endpoints
- Check: https://fiscaldata.treasury.gov/datasets/daily-treasury-statement/

**Wrong timezone?**
```bash
timedatectl set-timezone Europe/Berlin
timedatectl status
```

---

## DATA SOURCES (all free)

| Data | URL | Frequency |
|------|-----|-----------|
| RRP | fred.stlouisfed.org/series/RRPONTSYD | Daily |
| Reserves | fred.stlouisfed.org/series/WRESBAL | Weekly Wed |
| TGA | fiscaldata.treasury.gov | Daily 4pm EST |
| FSI | financialresearch.gov/financial-stress-index | Daily |
| ranto28 | rss.blog.naver.com/ranto28.xml | On new post |

---

## ALARM SCHEDULE

| Time (Berlin) | Brief |
|---------------|-------|
| **07:00** | 🔱 Full Liquidity Brief + FSI + Calendar + GOD Command |
| **13:30** | US Market Open |
| **16:30** | Midday Check |
| **19:00** | Market Close |
| **23:30** | Asia Open + ranto28 check |
| **Wed 07:00** | Full 3-index recalculation |

---

🔱 MINERVA · TITAN · OLYMPUS §11 · ISLAND MISSION 2036

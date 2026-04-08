#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# MINERVA VPS SETUP SCRIPT
# titan_K v2 — Full system deployment on Ubuntu 24.04
# Run as root: bash setup_minerva.sh
# ═══════════════════════════════════════════════════════════════

set -e  # Exit on any error

echo ""
echo "🔱 MINERVA VPS SETUP — titan_K v2"
echo "═══════════════════════════════════"
echo ""

# ── 1. System update ──────────────────────────────────────────
echo "[1/8] Updating system..."
apt-get update -qq && apt-get upgrade -y -qq
apt-get install -y -qq \
    python3 python3-pip python3-venv \
    git curl wget rsync \
    screen tmux \
    ufw fail2ban

echo "✅ System updated"

# ── 2. Create minerva user ────────────────────────────────────
echo "[2/8] Creating minerva user..."
if ! id "minerva" &>/dev/null; then
    useradd -m -s /bin/bash minerva
    echo "✅ User minerva created"
else
    echo "✅ User minerva already exists"
fi

# ── 3. Clone repo ─────────────────────────────────────────────
echo "[3/8] Cloning titan_K v2 repo..."
cd /home/minerva
if [ ! -d "titan_k_v2" ]; then
    sudo -u minerva git clone https://github.com/sobluenight10-commits/titan_k_v2.git
else
    sudo -u minerva git -C titan_k_v2 pull
fi
echo "✅ Repo ready"

# ── 4. Python venv + dependencies ────────────────────────────
echo "[4/8] Installing Python dependencies..."
cd /home/minerva/titan_k_v2
sudo -u minerva python3 -m venv venv
sudo -u minerva venv/bin/pip install --quiet --upgrade pip
sudo -u minerva venv/bin/pip install --quiet \
    openai \
    "python-telegram-bot==20.7" \
    schedule \
    pytz \
    python-dotenv \
    requests \
    beautifulsoup4 \
    feedparser \
    yfinance \
    pandas \
    numpy \
    "pydantic==1.10.13" \
    "anyio==3.5.0" \
    "openai==1.3.0" \
    nest_asyncio
echo "✅ Dependencies installed"

# ── 5. Create .env file ───────────────────────────────────────
echo "[5/8] Creating .env file..."
ENV_FILE="/home/minerva/titan_k_v2/.env"

if [ ! -f "$ENV_FILE" ]; then
cat > "$ENV_FILE" << 'ENVEOF'
OPENAI_API_KEY=YOUR_OPENAI_KEY_HERE
TELEGRAM_BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN_HERE
TELEGRAM_CHAT_ID=YOUR_TELEGRAM_CHAT_ID_HERE
TITAN_SYSTEM_URL=https://sobluenight10-commits.github.io/titan_k_v2/TITAN_SYSTEM_v4.html
ENVEOF
    chown minerva:minerva "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    echo "⚠️  .env created — YOU MUST EDIT IT with your real keys"
    echo "    Run: nano /home/minerva/titan_k_v2/.env"
else
    echo "✅ .env already exists — skipping"
fi

# ── 6. Create shared research folder (for TITAN to read) ──────
echo "[6/8] Creating shared research folder..."
mkdir -p /shared/research
chown minerva:minerva /shared/research
chmod 755 /shared/research
echo "✅ Shared research folder: /shared/research"

# ── 7. Create systemd service (auto-start + auto-restart) ────
echo "[7/8] Creating systemd service..."
cat > /etc/systemd/system/minerva.service << 'SERVICEEOF'
[Unit]
Description=Minerva — titan_K v2 Investment System
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=minerva
WorkingDirectory=/home/minerva/titan_k_v2
ExecStart=/home/minerva/titan_k_v2/venv/bin/python main.py
Restart=always
RestartSec=5
Nice=-10
Environment=PYTHONUNBUFFERED=1
MemoryMax=1G
StandardOutput=append:/home/minerva/titan_k_v2/minerva.log
StandardError=append:/home/minerva/titan_k_v2/minerva.log
# If Nice=-10 causes start failure, remove Nice= or set LimitNICE=infinity (see deploy/minerva.service)

[Install]
WantedBy=multi-user.target
SERVICEEOF

systemctl daemon-reload
systemctl enable minerva
echo "✅ Systemd service created (minerva.service)"

# ── 8. Firewall setup ─────────────────────────────────────────
echo "[8/8] Configuring firewall..."
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow from any to any port 443  # HTTPS outbound for APIs
ufw --force enable
echo "✅ Firewall configured (SSH only inbound)"

# ── Summary ───────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "✅ MINERVA VPS SETUP COMPLETE"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "NEXT STEPS:"
echo ""
echo "1. Edit your API keys:"
echo "   nano /home/minerva/titan_k_v2/.env"
echo ""
echo "2. Push your latest code from laptop:"
echo "   (on laptop) git add . && git commit -m 'deploy' && git push"
echo "   (on server) cd /home/minerva/titan_k_v2 && git pull"
echo ""
echo "3. Start Minerva:"
echo "   systemctl start minerva"
echo ""
echo "4. Check she's running:"
echo "   systemctl status minerva"
echo "   tail -f /home/minerva/titan_k_v2/minerva.log"
echo ""
echo "🔱 Minerva standing by."

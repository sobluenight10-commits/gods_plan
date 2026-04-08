# Remote development on Contabo (Cursor + Minerva)

## Order 1 — Titan-Link: SSH config (local machine)

In **Cursor on your laptop**:

1. **Ctrl+Shift+P** (Mac: **Cmd+Shift+P**)
2. Run **Remote-SSH: Open SSH Configuration File**
3. Add a host block (adjust user, hostname, or key path if yours differ):

```sshconfig
Host minerva-titan
    HostName vmd193173.contabo.host
    User root
    IdentityFile ~/.ssh/id_ed25519
    ConnectTimeout 60
    ServerAliveInterval 30
```

**Tip:** `ServerAliveInterval 30` sends periodic keepalives so idle Contabo sessions are less likely to drop while you edit.

4. **Remote-SSH: Connect to Host…** → choose `minerva-titan`
5. **File → Open Folder** → `/home/minerva/gods_plan` (or `/home/minerva/titan_k_v2` if you have not renamed on the server yet)

---

## Order 2 — Ghost protocol: Python interpreter (remote)

After you are connected to the remote workspace:

1. Click the **Python version** in the status bar, **or** **Ctrl+Shift+P** → **Python: Select Interpreter**
2. Choose: **`/home/minerva/gods_plan/venv/bin/python`**

If the venv does not exist yet:

```bash
cd /home/minerva/gods_plan
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

Project rules for the agent live in **`.cursorrules`** at the repo root.

---

## Order 3 — Shield of Minerva: systemd hardening

Hardened unit file template: **`deploy/minerva.service`**.

On the server (as root):

```bash
sudo cp /home/minerva/gods_plan/deploy/minerva.service /etc/systemd/system/minerva.service
# Edit paths inside the file if your repo is still titan_k_v2
sudo nano /etc/systemd/system/minerva.service
sudo systemctl daemon-reload
sudo systemctl restart minerva
sudo systemctl status minerva
```

Key **\[Service]** options in that file:

- `Restart=always` + `RestartSec=5` — auto-recover after crashes or stalls  
- `Nice=-10` — higher scheduling priority (within what the kernel allows)  
- `Environment=PYTHONUNBUFFERED=1` — real-time logs  
- `MemoryMax=1G` — cap RAM to reduce OOM risk on small VPS plans  

**Note:** `Nice=-10` often requires raising `LimitNICE=` or running with capabilities; if `systemctl start` fails, check `journalctl -xe` and relax `Nice` or add `AmbientCapabilities=CAP_SYS_NICE` only if you accept the tradeoff (see comments in `deploy/minerva.service`).

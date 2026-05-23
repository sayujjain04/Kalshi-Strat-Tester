#!/usr/bin/env bash
# One-time setup on an Oracle/GCP Always-Free Ubuntu VM.
# Run AFTER you've cloned the repo and put your key in .secrets/.
#   bash deploy/setup.sh [REPO_DIR]
set -e
REPO_DIR="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
USER_NAME="$(whoami)"
echo "Repo: $REPO_DIR   User: $USER_NAME"

echo "==> Installing deps"
sudo apt-get update -y
sudo apt-get install -y python3-pip git
pip3 install --user requests websockets cryptography

if [ ! -f "$REPO_DIR/.secrets/kalshi_key.pem" ]; then
  echo "⚠ Missing $REPO_DIR/.secrets/kalshi_key.pem"
  echo "  Put your key there first: key_id.txt + kalshi_key.pem (scp from local)."
  exit 1
fi

echo "==> Installing systemd services"
sudo tee /etc/systemd/system/paper-daemon.service >/dev/null <<EOF
[Unit]
Description=Kalshi paper-trading daemon (continuous, auto-tracks games)
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
WorkingDirectory=$REPO_DIR
ExecStart=/usr/bin/python3 $REPO_DIR/run_paper.py --daemon
Restart=always
RestartSec=30
User=$USER_NAME
[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/kalshi-dashboard.service >/dev/null <<EOF
[Unit]
Description=Kalshi dashboard (serves dashboard.html over HTTP)
[Service]
Type=simple
WorkingDirectory=$REPO_DIR
ExecStart=/usr/bin/python3 -m http.server 8000
Restart=always
User=$USER_NAME
[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now paper-daemon kalshi-dashboard
echo "==> Done."
echo "   Dashboard:  http://<YOUR_VM_PUBLIC_IP>:8000/dashboard.html"
echo "   Logs:       journalctl -u paper-daemon -f"
echo "   (Open port 8000 in the Oracle security list AND: sudo ufw allow 8000)"

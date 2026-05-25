#!/usr/bin/env bash
# One-time setup on an Oracle/GCP Always-Free Ubuntu VM.
# Run AFTER you've cloned the repo and put your key in .secrets/.
#   bash deploy/setup.sh [REPO_DIR]
set -e
REPO_DIR="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
USER_NAME="$(whoami)"
echo "Repo: $REPO_DIR   User: $USER_NAME"

echo "==> Installing deps (in a venv — robust across Ubuntu versions)"
sudo apt-get update -y
sudo apt-get install -y python3-pip python3-venv git
python3 -m venv "$REPO_DIR/.venv"
"$REPO_DIR/.venv/bin/pip" install -q --upgrade pip
"$REPO_DIR/.venv/bin/pip" install -q requests websockets cryptography
PY="$REPO_DIR/.venv/bin/python3"

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
ExecStart=$PY $REPO_DIR/run_paper.py --daemon
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
ExecStart=$PY -m http.server 8000
Restart=always
User=$USER_NAME
[Install]
WantedBy=multi-user.target
EOF

# the deterministic daily lab cycle (analyze + auto-tune auto_house + boards +
# report + commit). No LLM needed for this layer — plain cron/timer.
sudo tee /etc/systemd/system/lab-cycle.service >/dev/null <<EOF
[Unit]
Description=Kalshi lab cycle (analyze, auto-tune, boards, report, commit)
[Service]
Type=oneshot
WorkingDirectory=$REPO_DIR
ExecStart=$PY $REPO_DIR/lab_cycle.py
User=$USER_NAME
EOF
sudo tee /etc/systemd/system/lab-cycle.timer >/dev/null <<EOF
[Unit]
Description=Run the Kalshi lab cycle daily
[Timer]
OnCalendar=*-*-* 09:00:00 UTC
Persistent=true
[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now paper-daemon kalshi-dashboard
sudo systemctl enable --now lab-cycle.timer
echo "==> Done."
echo "   Boards:     http://<YOUR_VM_PUBLIC_IP>:8000/boards.html"
echo "   Game shard: http://<YOUR_VM_PUBLIC_IP>:8000/dashboards/<game_id>.html"
echo "   Logs:       journalctl -u paper-daemon -f   (and -u lab-cycle)"
echo "   (Open port 8000 in the Oracle security list AND: sudo ufw allow 8000)"

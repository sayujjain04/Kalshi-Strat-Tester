#!/usr/bin/env bash
# One-time setup on a GCP e2-micro (Always-Free) Ubuntu VM.
# Run AFTER the repo is cloned and .secrets/ has key_id.txt + kalshi_key.pem
# (+ gh_token.txt for pushing). Board is served by GitHub Pages, NOT this VM —
# so no inbound web server / no open ports beyond SSH.
#   bash deploy/setup.sh [REPO_DIR]
set -e
REPO_DIR="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
USER_NAME="$(whoami)"
REPO_SLUG="${REPO_SLUG:-sayujjain04/Kalshi-Strat-Tester}"
echo "Repo: $REPO_DIR   User: $USER_NAME"

echo "==> Installing deps (in a venv — robust across Ubuntu versions)"
sudo apt-get update -y
sudo apt-get install -y python3-pip python3-venv git
python3 -m venv "$REPO_DIR/.venv"
"$REPO_DIR/.venv/bin/pip" install -q --upgrade pip
"$REPO_DIR/.venv/bin/pip" install -q requests websockets cryptography
PY="$REPO_DIR/.venv/bin/python3"

if [ ! -f "$REPO_DIR/.secrets/kalshi_key.pem" ]; then
  echo "⚠ Missing $REPO_DIR/.secrets/kalshi_key.pem — scp your key first."; exit 1
fi

echo "==> Configuring git (identity + token-authed push remote)"
git -C "$REPO_DIR" config user.email "lab-vm@users.noreply.github.com"
git -C "$REPO_DIR" config user.name  "kalshi-lab-vm"
git -C "$REPO_DIR" config pull.rebase true
if [ -f "$REPO_DIR/.secrets/gh_token.txt" ]; then
  TOK="$(tr -d '\n' < "$REPO_DIR/.secrets/gh_token.txt")"
  git -C "$REPO_DIR" remote set-url origin "https://${TOK}@github.com/${REPO_SLUG}.git"
  echo "   push remote set (token hidden)"
else
  echo "   ⚠ no .secrets/gh_token.txt — daemon will capture but can't push results"
fi

echo "==> Installing systemd services"
# Continuous capture daemon: watches for games 24/7, captures concurrently,
# pushes raw game data to the repo periodically.
sudo tee /etc/systemd/system/paper-daemon.service >/dev/null <<EOF
[Unit]
Description=Kalshi paper-trading daemon (continuous, auto-tracks all games)
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

# Daily "brain": analyze + guarded auto-tune + rebuild board + push (vm_cycle.sh).
sudo tee /etc/systemd/system/lab-cycle.service >/dev/null <<EOF
[Unit]
Description=Kalshi lab cycle (analyze, auto-tune, board, report, push)
[Service]
Type=oneshot
WorkingDirectory=$REPO_DIR
Environment=PY=$PY
ExecStart=/usr/bin/env bash $REPO_DIR/deploy/vm_cycle.sh
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
sudo systemctl enable --now paper-daemon
sudo systemctl enable --now lab-cycle.timer
echo "==> Done."
echo "   Board (GitHub Pages): https://sayujjain04.github.io/Kalshi-Strat-Tester/"
echo "   Daemon logs:  journalctl -u paper-daemon -f"
echo "   Cycle logs:   journalctl -u lab-cycle -f   (runs daily 09:00 UTC)"
echo "   Run cycle now: sudo systemctl start lab-cycle"

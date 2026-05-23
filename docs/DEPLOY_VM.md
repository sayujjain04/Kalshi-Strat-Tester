# Deploy to an Oracle Always-Free VM (always-on paper + live dashboard)

This runs the paper daemon 24/7 on a free Oracle VM: it auto-tracks every NBA
game from tip-off, serves a live dashboard you can open from anywhere, and pushes
each game's data to the repo. **Paper only — real trading (`run_real.py`) stays on
your laptop, attended.**

## 1. Create the free VM (one-time)
1. cloud.oracle.com → sign up (free; needs a card but Always-Free isn't charged).
2. Create a **VM instance** → shape **Always Free eligible** (Ampere ARM or AMD
   Micro), image **Ubuntu 22.04**. Download the SSH key.
3. Networking → the VCN's **security list** → add an **ingress rule**: TCP port
   **8000** from `0.0.0.0/0` (so you can view the dashboard).

## 2. Set it up
SSH in (`ssh -i your-key ubuntu@<VM_PUBLIC_IP>`), then:

```bash
# clone the repo
git clone https://github.com/sayujjain04/Kalshi-Strat-Tester.git
cd Kalshi-Strat-Tester

# put your key on the VM (run these FROM YOUR LAPTOP, not the VM):
#   scp -i your-key .secrets/key_id.txt    ubuntu@<VM_IP>:~/Kalshi-Strat-Tester/.secrets/
#   scp -i your-key .secrets/kalshi_key.pem ubuntu@<VM_IP>:~/Kalshi-Strat-Tester/.secrets/
# (mkdir .secrets on the VM first if needed)

# let the daemon push data back to the repo (use a GitHub token):
git remote set-url origin https://<YOUR_GITHUB_TOKEN>@github.com/sayujjain04/Kalshi-Strat-Tester.git
git config user.name "vm-paper"; git config user.email "vm@users.noreply.github.com"

# install + start the services
bash deploy/setup.sh
sudo ufw allow 8000 || true
```

## 3. Use it
- **Live dashboard:** `http://<VM_PUBLIC_IP>:8000/dashboard.html` — open it any time,
  any device. It updates as games run.
- **Logs:** `journalctl -u paper-daemon -f`
- **Data:** each finished game is pushed to `data/games/` in the repo. Locally,
  `git pull` then `python3 summary.py` / `analyze.py` / `history.py`.

## Notes
- The daemon auto-tracks the current live game (or waits for the soonest upcoming
  one) — no cron, no timing problem. This replaces GitHub Actions as the primary
  always-on path (Actions remains an optional backup).
- The dashboard server is plain HTTP on a single port; anyone with the IP can view
  it. Fine for a personal paper dashboard; lock it down (firewall to your IP, or
  add auth) if you care.
- **Real money never runs here.** `run_real.py` is laptop-only and attended.
- Restart services after `git pull` of code changes: `sudo systemctl restart paper-daemon kalshi-dashboard`.

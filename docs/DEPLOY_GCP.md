# Deploy to a free GCP VM (always-on paper lab + board)

Runs the lab 24/7 on a Google Cloud `e2-micro` (Always Free, forever). Paper only.

## 1. Account + project
1. Go to **console.cloud.google.com**, sign in, start the free trial (needs a card;
   the e2-micro is free regardless of the trial credit).
2. Top bar → create/select a project (any name).

## 2. Create the VM (must be a free-tier region)
**Compute Engine → VM instances → Create instance** (enable the API if prompted):
- **Name:** `kalshi-lab`
- **Region:** `us-central1` (or `us-west1` / `us-east1` — only these are Always Free)
- **Machine type:** Series **E2** → **`e2-micro`**  ← the free one
- **Boot disk:** Change → **Ubuntu 22.04 LTS**, size **30 GB** (free tier limit)
- Click **Create**. Note the **External IP** in the instance list.

## 3. Open port 8000 (so you can see the board)
**VPC network → Firewall → Create firewall rule:**
- Name `allow-8000` · Direction **Ingress** · Targets **All instances** ·
  Source IPv4 `0.0.0.0/0` · Protocols/ports **TCP `8000`** → Create.
- (For privacy, set Source to *your* IP instead of `0.0.0.0/0`.)

## 4. SSH in
In the VM list, click the **SSH** button (opens a browser terminal — no key setup).

## 5. Install the lab
```bash
sudo apt-get update -y && sudo apt-get install -y git
git clone https://github.com/sayujjain04/Kalshi-Strat-Tester.git
cd Kalshi-Strat-Tester
```

## 6. Add your Kalshi key (paste — browser SSH has no scp)
On the VM:
```bash
mkdir -p .secrets
nano .secrets/key_id.txt        # paste your key id, then Ctrl+O Enter Ctrl+X
nano .secrets/kalshi_key.pem    # paste the WHOLE PEM block, then Ctrl+O Enter Ctrl+X
```
Get the values from **your Mac** with: `cat .secrets/key_id.txt` and
`cat .secrets/kalshi_key.pem` (copy the full `-----BEGIN…END-----`).

## 7. Run the installer
```bash
bash deploy/setup.sh
sudo ufw allow 8000 2>/dev/null || true
```
Installs deps in a venv and starts: the **multi-game capture daemon**, the
**dashboard server**, and the **daily lab-cycle timer**.

## 8. Open your board
`http://<EXTERNAL_IP>:8000/boards.html` — bookmark it. Per-game shards are at
`/dashboards/<game_id>.html`.

## Check / manage
```bash
journalctl -u paper-daemon -f      # live capture log
systemctl status paper-daemon kalshi-dashboard lab-cycle.timer
git pull && sudo systemctl restart paper-daemon kalshi-dashboard   # after code updates
```

## Notes
- **Paper only** here — no real money, so the open port is low-risk.
- e2-micro is 1 GB RAM; the lab is light enough. If it ever OOMs with many
  simultaneous games, tell me and we'll cap concurrency.
- **Optional — push data back to the repo** (so you can `git pull` locally):
  ```bash
  git remote set-url origin https://<GITHUB_TOKEN>@github.com/sayujjain04/Kalshi-Strat-Tester.git
  git config user.name vm-paper; git config user.email vm@users.noreply.github.com
  ```
  Without this the daemon just skips pushing (board still works on the VM).

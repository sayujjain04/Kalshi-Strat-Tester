# Deploy the paper tracker to GitHub Actions (free, laptop-off)

This runs `run_paper.py` headless on GitHub's servers during a game and commits
the game's logs back to your repo. No server, no cost, no laptop needed.

Your Kalshi key is **not** in the code — it lives in `.secrets/` locally (gitignored)
and in GitHub as encrypted **secrets**.

## One-time setup

### 1. Create the repo
On github.com → New repository. **Make it Public** → GitHub Actions minutes are
*unlimited* on public repos (private = 2000 min/month, which a few games can eat).
The code is safe to be public — your key is a secret, never in the code.

### 2. Add your key as two secrets
Repo → **Settings → Secrets and variables → Actions → New repository secret**. Add:

- **`KALSHI_KEY_ID`** — paste the contents of your local file `.secrets/key_id.txt`
- **`KALSHI_PEM`** — paste the *entire* contents of `.secrets/kalshi_key.pem`
  (the whole block, `-----BEGIN…` through `…END-----`, multiple lines is fine)

To see the values to copy:
```
cat .secrets/key_id.txt
cat .secrets/kalshi_key.pem
```

### 3. Push the code
```
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
```
(`.secrets/` is gitignored, so your key is NOT uploaded — only the secrets you
pasted in step 2 are used.)

## Running it

- **Manual (recommended):** repo → **Actions** tab → "paper-tracker" → **Run workflow**.
  Trigger it around tip-off; it auto-picks the live/upcoming game and runs until
  the game ends, then commits the logs.
- **Scheduled:** the workflow has a daily `cron` (23:30 UTC ≈ 6:30pm ET). Edit or
  remove it in `.github/workflows/paper.yml`. On non-game days it finds nothing
  and exits in seconds.

You can trigger "Run workflow" from the GitHub mobile app too — phone, no laptop.

## Where the data lands
Each game commits to `data/games/<date>_<away>_<home>/` in the repo — browse it on
github.com (ticks, trades, plays, decisions, meta.json). Pull it down anytime:
```
git pull
```

## Notes
- This is **paper only** — no real orders. (Real money via `run_real.py` stays
  local/attended; don't put it in CI.)
- GitHub cron can fire a few minutes late; for a precise start, use Run workflow.
- If a run is cut at the 6h cap, logs up to that point are still committed.

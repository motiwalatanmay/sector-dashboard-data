# Sector Dashboard Pipeline — Setup Guide

## Prerequisites

```bash
pip install requests yfinance
```

No other libraries needed. `yfinance` is only used as a price-only fallback
if NSE India's API is unavailable; the pipeline works without it.

---

## File structure

```
sector_pipeline/
├── config.py          ← all settings (edit this first)
├── data_fetch.py      ← NSE scraper + yfinance fallback
├── pipeline.py        ← stats engine + JSON writer
├── github_push.py     ← GitHub Contents API uploader
├── run_pipeline.py    ← daily orchestrator (Task Scheduler calls this)
├── bootstrap.py       ← one-time seed for sector_data.json
├── schedule_setup.bat ← registers the Windows Task Scheduler task
├── pipeline.log       ← auto-created on first run
└── sector_data.json   ← auto-created; pushed to GitHub daily
```

---

## One-time setup (do this once)

### Step 1 — Create a GitHub repo

1. Go to https://github.com/new
2. Name it `sector-dashboard-data` (public or private — both work)
3. Leave it empty (no README, no .gitignore)

### Step 2 — Generate a Personal Access Token

1. GitHub → Settings → Developer settings → Personal access tokens → Fine-grained
2. Repository access: select `sector-dashboard-data` only
3. Permissions → Repository permissions → Contents: **Read and write**
4. Copy the token (shown only once)

### Step 3 — Edit config.py

```python
GITHUB_TOKEN = "ghp_your_token_here"
GITHUB_USER  = "your-github-username"
GITHUB_REPO  = "sector-dashboard-data"
```

**Safer alternative** (token not in code): open a terminal and run:
```
setx GITHUB_TOKEN "ghp_your_token_here"
setx GITHUB_USER  "your-github-username"
setx GITHUB_REPO  "sector-dashboard-data"
```
Restart your terminal after `setx`. `config.py` reads these via `os.getenv`.

### Step 4 — Seed the initial data (bootstrap)

Copy `sector_data.json` from your dashboard project into this folder.
If you don't have one yet, open `bootstrap.py`, paste the `EMBEDDED_DATA`
dict from `sector_dashboard_fixed.jsx`, and run:

```bash
python bootstrap.py
```

### Step 5 — Test the full pipeline manually

```bash
python run_pipeline.py
```

Expected output (abbreviated):
```
2026-04-06 16:15:00  INFO  ─────────────────────────────
2026-04-06 16:15:00  INFO  Pipeline started  2026-04-06 16:15 IST
2026-04-06 16:15:00  INFO  [1/3]  Fetching from NSE India…
2026-04-06 16:15:04  INFO         NSE allIndices: got 56 entries
2026-04-06 16:15:04  INFO    ✓  NIFTY 50                  price=22819.6  pe=21.57  earn=1057.93
...
2026-04-06 16:15:35  INFO  [2/3]  Running pipeline…
2026-04-06 16:15:35  INFO         Saved sector_data.json  (85 KB)
2026-04-06 16:15:35  INFO  [3/3]  Pushing to GitHub…
2026-04-06 16:15:37  INFO         GitHub push OK  →  https://raw.githubusercontent.com/...
```

### Step 6 — Wire up the dashboard

After the first successful push, your raw URL will be:

```
https://raw.githubusercontent.com/YOUR_USER/sector-dashboard-data/main/sector_data.json
```

Open `sector_dashboard_fixed.jsx` and set:

```js
const REMOTE_DATA_URL = "https://raw.githubusercontent.com/YOUR_USER/sector-dashboard-data/main/sector_data.json";
```

Re-publish the artifact. The dashboard will now show `● LIVE` and fetch
fresh data on every page load (GitHub raw CDN has ~5 min cache).

### Step 7 — Schedule daily at 4:15 PM

1. Open `schedule_setup.bat` in Notepad
2. Edit `PYTHON_EXE` to match your Python installation path
3. Edit `SCRIPT_DIR` to this folder's path
4. Right-click `schedule_setup.bat` → **Run as administrator**

Verify:
```bash
schtasks /query /tn SectorDashboardPipeline
```

Test immediately:
```bash
schtasks /run /tn SectorDashboardPipeline
```

---

## Daily operation

At 4:15 PM IST every trading day, Task Scheduler calls `run_pipeline.py`:

1. **NSE session warm-up** (hits homepage to get cookies)
2. **`allIndices` API call** — bulk fetch of all index data in one request
3. **Per-sector processing** — derives earnings (E = P/PE), upserts ts
4. **Stats recompute** — medianPE, CAGR, earnTrend, valuationGap all recalculated from full ts
5. **sector_data.json saved** locally
6. **GitHub push** — Contents API PUT updates the file in your repo
7. Dashboard fetches the new JSON on its next page load

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `NSE allIndices failed: 403` | NSE blocked the request | Wait 1 hour, retry; NSE rate-limits aggressively |
| `pe=None` for a sector | NSE doesn't publish PE for that index | Sector is skipped that day; historical stats unchanged |
| `GitHub: PUT failed 422` | SHA mismatch | File was modified externally; pipeline will self-correct next run |
| Dashboard still shows `EMBEDDED` | REMOTE_DATA_URL not set | Confirm the const is set and re-publish the artifact |
| `sector_data.json` not found | Forgot bootstrap | Run `python bootstrap.py` first |

Check `pipeline.log` for detailed per-run logs.

---

## Notes

- NSE doesn't publish PE for all sector indices (e.g. NIFTY REALTY sometimes
  returns `pe=null`). The pipeline logs a warning and skips the ts append for
  that day — the sector's historical data is preserved unchanged.
- `sector_data.json` is compact JSON (no indentation) to keep the file small
  for GitHub's raw CDN.  The dashboard parses it correctly.
- The pipeline is idempotent: running it twice on the same day updates the
  same date_key entry rather than duplicating it.

# Median PE Upgrade — Single Source of Truth (Screener.in)

Date: 2026-04-06
Owner: Dr Tanmay Motiwala

## What changed

**Problem:** The dashboard was showing three different "3Y/5Y/10Y median PE"
numbers for the same sector:

1. `stats.med3 / med5 / medianPE` — computed locally by `pipeline.py` from the
   `ts` array (short history, ~5 years max, noisy).
2. `current.median3y / 5y / 10y` — hardcoded / manually pasted from Screener.
3. `stats.modelMedianPE` — a validation cross-check.

The chart reference line used #1, the KPI cards used #2, and the signal
engine mixed both. For NIFTY BANK, #1 showed 17.43 vs #2 showing 23.6 —
the chart and the decision signal disagreed on where "fair value" sat.

**Fix:** Screener.in is now the **single source of truth** for all
median PE values. A new Python scraper (`scrape_medians.py`) hits
Screener's chart API directly and refreshes `medians_curated.json` every
day before the main pipeline runs. The JSX adapter reads medians from
`current.*` only; `stats.med*` is retained solely as an outlier-filter
bound for the chart.

## Files changed / added

| File | Change |
|---|---|
| `scrape_medians.py` *(new)* | Python HTTP scraper hitting Screener's `/api/company/{id}/chart/` endpoint for 3Y/5Y/10Y medians. Replaces the browser-console `scrape_medians.js` workflow. |
| `pipeline.py` | Added NSE sanity check (flags >10% deviation between NSE live PE and Screener 10Y), freshness stamping (`mediansSource`, `dataStale`, `nseMismatch`). |
| `run_pipeline.py` | New Step 0 runs `scrape_medians.main()` before the NSE fetch. Fails loud but non-fatal — keeps yesterday's `medians_curated.json`. |
| `sector_dashboard_patched.jsx` | `mapSectorData` now treats `cur.median10y` as the unified `medianPE`. Added `<StaleDataBanner>` component shown in `DetailPanel` when data is stale or NSE mismatch detected. `peCap` chart filter now uses `statsPeCap` (preserved ts-based bound) to keep chart scale sane. |
| `MEDIAN_UPGRADE_NOTES.md` *(new)* | This file. |

## How Screener scraping works

Screener's company/index page embeds a chart that fetches JSON from:

```
GET https://www.screener.in/api/company/{company_id}/chart/
    ?q=Index+PE-Median+Index+PE
    &days={1096|1826|3652}
```

Response shape:

```json
{
  "datasets": [
    { "metric": "Index PE",        "values": [["2016-04-06","22.1"], ...] },
    { "metric": "Median Index PE", "label": "Median Index PE = 23.4",
      "values": [["2016-04-06","23.4"], ["2026-04-02","23.4"]] }
  ]
}
```

The 10Y median is parsed from `label` (`Median Index PE = X`) with a
regex fallback to `values[0][1]`. The 14 sector → company_id mappings
are baked into `SECTOR_IDS` in `scrape_medians.py`, discovered from the
`data-company-id` attribute on each `/company/<slug>/` page.

### Company ID map

| Sector | Company ID | Slug |
|---|---|---|
| NIFTY 50 | 1272594 | NIFTY |
| NIFTY NEXT 50 | 1272613 | NIFTYJR |
| NIFTY SMALLCAP 250 | 1275142 | NIFTYSMLCAP250 |
| NIFTY MICROCAP 250 | 1284386 | NIFTYMCAP250 |
| NIFTY BANK | 1272670 | BANKNIFTY |
| NIFTY PSU BANK | 1272693 | CNXPSUBANK |
| NIFTY AUTO | 1272796 | CNXAUTO |
| NIFTY REALTY | 1272692 | CNXREALTY |
| NIFTY IT | 1272649 | CNXIT |
| NIFTY INFRA | 1272689 | CNXINFRAST |
| NIFTY PHARMA | 1272672 | CNXPHARMA |
| NIFTY FMCG | 1272711 | CNXFMCG |
| NIFTY METAL | 1272797 | CNXMETAL |
| NIFTY ENERGY | 1272671 | CNXENERY |

## Installation & running (macOS)

No new dependencies. `scrape_medians.py` uses `requests`, which is
already in the pipeline. If it's missing: `pip3 install requests`.

```bash
cd "/Users/drtanmaymotiwala/Documents/Sector_pipeline"

# Dry run (print JSON, don't overwrite file)
python3 scrape_medians.py --dry-run

# Write to medians_curated.json
python3 scrape_medians.py

# Or just run the full orchestrator — scraper is Step 0
python3 run_pipeline.py
```

Your existing 5 PM IST daily schedule (launchd or crontab) needs no
change — the scraper runs as part of `run_pipeline.py`. To check which
scheduler is driving it:

```bash
# cron
crontab -l

# launchd
launchctl list | grep -i sector
ls ~/Library/LaunchAgents/ | grep -i sector
```

### Optional: paid-tier authentication

If Screener ever gates 10Y data behind login (it currently doesn't for
the chart API), set your session cookie in `config.py`:

```python
SCREENER_SESSION_COOKIE = "sessionid=YOUR_SESSION_ID_HERE"
```

Or via env var — add to `~/.zshrc`:

```bash
export SCREENER_SESSION_COOKIE="sessionid=YOUR_VALUE"
```

Then `source ~/.zshrc`. `scrape_medians.py` will pick it up automatically.

To get the cookie: open Chrome DevTools on `screener.in`, Application tab
→ Cookies → `https://www.screener.in` → copy the `sessionid` value.

## Fail-loud behaviour

- If **any** sector's median scrape fails (network error, parse error,
  etc.), `scrape_medians.py` aborts with exit code 2 and leaves
  `medians_curated.json` **untouched** (yesterday's file is preserved).
- `run_pipeline.py` catches the non-zero exit and logs a loud ERROR but
  continues with the rest of the pipeline.
- The pipeline stamps `mediansSource = "stale"` on every sector in the
  output JSON.
- The JSX dashboard reads `dataStale` and renders a yellow `<StaleDataBanner>`
  inside the Sector Detail panel explaining why the numbers are old.
- A backup copy of the previous file is kept at `medians_curated.backup.json`.

## NSE sanity check

After Screener medians are applied, `pipeline.py` compares the live NSE
`marketPE` against Screener's 10Y median. If `|NSE - Scr10Y| / Scr10Y > 10%`:

- Log a WARNING with the two numbers.
- Set `cur.nseMismatch = <deviation ratio>`.
- The dashboard shows a second line in the banner:
  *"NSE live PE vs Screener 10Y median deviates 14% — check data plumbing"*

Note: this is a **plumbing sanity check**, not a valuation signal. A
sector legitimately trading 40% below its 10Y median (cheap zone) will
NOT trigger this — because NSE PE and Screener 10Y median are expected
to diverge during cheap/expensive regimes. The check is set loose
(>10%) specifically to catch cases like wrong `company_id`, stale
Screener scale, or NSE API returning garbage.

If you find the 10% threshold too tight in practice, adjust this line
in `pipeline.py`:

```python
if dev > 0.10:   # ← raise to 0.15 or 0.20 if too noisy
```

## Things NOT touched (intentionally)

- `stats.med3 / med5 / medianPE` are still computed in `pipeline.py`.
  They're used for the chart's y-axis outlier clipping (`statsPeCap`)
  so Screener 10Y being far from ts distribution doesn't squash the chart.
  They are **not** read by any KPI, signal, or decision logic anymore.
- `data_fetch.py` is unchanged — NSE fetching logic is independent.
- `github_push.py` is unchanged — still pushes `sector_data.json`.

## Testing the dashboard

1. Run `python scrape_medians.py --dry-run` and verify all 14 sectors
   return 3Y/5Y/10Y values (no `None`).
2. Run `python run_pipeline.py` end-to-end.
3. Open the dashboard — the chart's median reference line should now
   match the KPI card's "Med PE" value for every sector. (Before this
   fix, they disagreed by up to 6 points on NIFTY BANK.)
4. Temporarily break the scraper (rename `medians_curated.json` to
   force `missing`, or edit the file's `scraped_at` to yesterday) and
   confirm the yellow banner appears in the sector detail panel.

## Sources

- Screener chart endpoint (verified 2026-04-06): https://www.screener.in/api/company/1272594/chart/?q=Index+PE-Median+Index+PE&days=3652
- NIFTY NEXT 50 example page: https://www.screener.in/company/NIFTYJR/
- GitHub JSON host (dashboard reads from): https://raw.githubusercontent.com/motiwalatanmay/sector-dashboard-data/main/sector_data.json

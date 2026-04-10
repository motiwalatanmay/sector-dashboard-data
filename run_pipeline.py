"""
run_pipeline.py — daily orchestrator.

Execution order:
  0. scrape_medians  →  refresh medians_curated.json from Screener (fail-loud: if scrape
                        fails, KEEPS yesterday's file and dashboard shows stale banner)
  1. data_fetch      →  NSE + yfinance (with anti-block delays)
  2. pipeline        →  update sector_data.json + recompute stats
  3. github_push     →  upload to GitHub so dashboard can fetch via REMOTE_DATA_URL

Windows Task Scheduler calls:
  python  C:\\path\\to\\pipeline\\run_pipeline.py

Logs to both console and pipeline.log.
"""
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── Logging setup (must be before any other imports from this package) ──────────
IST      = timezone(timedelta(hours=5, minutes=30))
LOG_FILE = Path(__file__).parent / "pipeline.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


def _banner(msg: str) -> None:
    log.info("─" * 60)
    log.info(msg)
    log.info("─" * 60)


def main() -> int:
    _banner(f"Pipeline started  {datetime.now(IST).strftime('%Y-%m-%d %H:%M IST')}")

    # ── Step 0: Refresh Screener medians (fail-loud, keeps yesterday on error) ──
    log.info("\n[0/4]  Refreshing Screener medians…")
    try:
        from scrape_medians import main as scrape_main
        rc = scrape_main()
        if rc == 0:
            log.info("       Medians refreshed successfully")
        else:
            log.error("       Screener scrape FAILED (rc=%d) — keeping yesterday's "
                      "medians_curated.json; dashboard will show stale banner", rc)
    except Exception as exc:
        log.exception(f"Scraper step crashed (non-fatal): {exc}")
        log.error("       Keeping yesterday's medians_curated.json")

    # ── Step 1: Fetch ────────────────────────────────────────────────────────
    log.info("\n[1/4]  Fetching from NSE India…")
    try:
        from data_fetch import fetch_all
        fetch_data  = fetch_all()
        ok_count    = sum(1 for v in fetch_data.values() if v.get("price"))
        total       = len(fetch_data)
        log.info(f"       {ok_count}/{total} sectors with live data")
        if ok_count == 0:
            log.error("       Zero sectors fetched — aborting pipeline")
            return 1
    except Exception as exc:
        log.exception(f"Fetch step failed: {exc}")
        return 1

    # ── Step 2: Pipeline ────────────────────────────────────────────────────
    log.info("\n[2/4]  Running pipeline (append ts → recompute stats → save JSON)…")
    try:
        from pipeline import run_pipeline
        db = run_pipeline(fetch_data)

        # Print a short summary table
        log.info("\n  Sector                    PE      Med5    Gap     Class")
        log.info("  " + "─" * 60)
        for name, sec in db.get("sectors", {}).items():
            cur  = sec.get("current", {})
            pe   = cur.get("pe")   or "—"
            med5 = cur.get("median5y") or "—"
            gap  = cur.get("valuationGap")
            cls  = cur.get("classification", "—")
            gap_str = f"{gap:+.1%}" if isinstance(gap, float) else "—"
            log.info(f"  {name:25s}  {str(pe):6}  {str(med5):7}  {gap_str:7}  {cls}")
    except Exception as exc:
        log.exception(f"Pipeline step failed: {exc}")
        return 1

    # ── Step 3: GitHub push ─────────────────────────────────────────────────
    log.info("\n[3/4]  Pushing to GitHub…")
    try:
        from github_push import push_to_github
        success = push_to_github()
        if success:
            log.info("       Push successful — dashboard will fetch new data on next load")
        else:
            log.warning("       Push failed — data saved locally but NOT on GitHub")
            log.warning("       Dashboard will continue using its embedded/cached data")
    except Exception as exc:
        log.exception(f"GitHub push step error: {exc}")
        # Don't return non-zero here — data is saved locally, push can be retried

    _banner(f"Pipeline finished  {datetime.now(IST).strftime('%Y-%m-%d %H:%M IST')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

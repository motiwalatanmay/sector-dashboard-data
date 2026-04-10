"""
scrape_medians.py  —  automated Screener.in median-PE scraper.

Replaces the manual `scrape_medians.js` browser workflow with a pure-Python
HTTP call to Screener's chart endpoint:

    GET /api/company/{company_id}/chart/?q=Index+PE-Median+Index+PE&days={days}

For each sector we hit 3 endpoints (days=1096 / 1826 / 3652 for 3Y/5Y/10Y),
parse the 'Median Index PE = X' value, and write the result to
`medians_curated.json`.

Auth: the endpoint works anonymously for most indices, but Screener's paid
plan unlocks longer history on some. If SCREENER_SESSION_COOKIE is set in
config.py (or env), we send it to get full 10Y data.

Failure handling: if ANY sector fails to scrape, the script logs loudly,
KEEPS the existing medians_curated.json untouched, and returns a non-zero
exit code. Stale data is never silently written.

Usage:
    python scrape_medians.py             # scrapes all, writes file
    python scrape_medians.py --dry-run   # scrapes, prints, does not write
"""
from __future__ import annotations

import json
import logging
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import requests

log = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
BASE_DIR     = Path(__file__).parent
OUTPUT_FILE  = BASE_DIR / "medians_curated.json"
BACKUP_FILE  = BASE_DIR / "medians_curated.backup.json"

# ── Screener company ID registry ─────────────────────────────────────────────
# Discovered 2026-04-06 by inspecting Screener's data-company-id attribute on
# each /company/<slug>/ page. Slugs kept for reference; only IDs are used.
SECTOR_IDS: dict[str, dict] = {
    "NIFTY 50":           {"id": 1272594, "slug": "NIFTY"},
    "NIFTY NEXT 50":      {"id": 1272613, "slug": "NIFTYJR"},
    "NIFTY SMALLCAP 250": {"id": 1275142, "slug": "NIFTYSMLCAP250"},
    "NIFTY MICROCAP 250": {"id": 1284386, "slug": "NIFTYMCAP250"},
    "NIFTY BANK":         {"id": 1272670, "slug": "BANKNIFTY"},
    "NIFTY PSU BANK":     {"id": 1272693, "slug": "CNXPSUBANK"},
    "NIFTY AUTO":         {"id": 1272796, "slug": "CNXAUTO"},
    "NIFTY REALTY":       {"id": 1272692, "slug": "CNXREALTY"},
    "NIFTY IT":           {"id": 1272649, "slug": "CNXIT"},
    "NIFTY INFRA":        {"id": 1272689, "slug": "CNXINFRAST"},
    "NIFTY PHARMA":       {"id": 1272672, "slug": "CNXPHARMA"},
    "NIFTY FMCG":         {"id": 1272711, "slug": "CNXFMCG"},
    "NIFTY METAL":        {"id": 1272797, "slug": "CNXMETAL"},
    "NIFTY ENERGY":       {"id": 1272671, "slug": "CNXENERY"},
}

# Screener days → human window mapping
DAYS = {"median3y": 1096, "median5y": 1826, "median10y": 3652}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
    "Referer":         "https://www.screener.in/",
}

MEDIAN_LABEL_RE = re.compile(r"Median\s*(?:Index\s*)?PE\s*=\s*([\d.]+)", re.I)


def _make_session() -> requests.Session:
    """Build a Session, optionally with paid-tier auth cookie from config."""
    s = requests.Session()
    s.headers.update(HEADERS)

    # Optional: paid-tier session cookie for longer history on some indices.
    # Set in config.py as SCREENER_SESSION_COOKIE = "sessionid=..." or in env.
    cookie = None
    try:
        from config import SCREENER_SESSION_COOKIE  # type: ignore
        cookie = SCREENER_SESSION_COOKIE
    except Exception:
        import os
        cookie = os.getenv("SCREENER_SESSION_COOKIE")

    if cookie:
        # Cookie string can be "sessionid=xxx" or "sessionid=xxx; csrftoken=yyy"
        for part in cookie.split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                s.cookies.set(k, v, domain=".screener.in")
        log.info("screener: using authenticated session cookie")
    return s


def fetch_median(session: requests.Session, company_id: int, days: int,
                 retries: int = 3, backoff: float = 1.5) -> Optional[float]:
    """
    Hit the Screener chart endpoint and return the median PE for `days`.
    Parses the 'Median Index PE = X' label; falls back to values[0][1].
    Returns None on failure after all retries.
    """
    url = f"https://www.screener.in/api/company/{company_id}/chart/"
    params = {"q": "Index PE-Median Index PE", "days": days}

    for attempt in range(1, retries + 1):
        try:
            r = session.get(url, params=params, timeout=15)
            r.raise_for_status()
            data = r.json()
            datasets = data.get("datasets", [])
            med_ds = next(
                (d for d in datasets if "median" in (d.get("label", "") or "").lower()
                 or d.get("metric") == "Median Index PE"),
                None,
            )
            if not med_ds:
                # Some stock pages use "Price to Earning" / "Median PE" instead
                med_ds = next(
                    (d for d in datasets if d.get("metric") in ("Median PE", "Median Index PE")),
                    None,
                )
            if not med_ds:
                log.warning("  no median dataset for id=%s days=%s", company_id, days)
                return None

            # Primary: label parse
            label = med_ds.get("label", "") or ""
            m = MEDIAN_LABEL_RE.search(label)
            if m:
                return round(float(m.group(1)), 2)

            # Fallback: first value in the 2-point horizontal median line
            vals = med_ds.get("values") or []
            if vals and len(vals[0]) >= 2:
                return round(float(vals[0][1]), 2)

            log.warning("  could not parse median from id=%s days=%s", company_id, days)
            return None

        except (requests.RequestException, ValueError) as e:
            if attempt == retries:
                log.error("  id=%s days=%s failed after %d attempts: %s",
                          company_id, days, retries, e)
                return None
            sleep = backoff ** attempt
            log.warning("  id=%s days=%s attempt %d failed (%s), retry in %.1fs",
                        company_id, days, attempt, e, sleep)
            time.sleep(sleep)
    return None


def scrape_all() -> dict:
    """
    Scrape 3Y/5Y/10Y medians for all sectors.
    Returns dict with schema matching medians_curated.json.
    Raises RuntimeError if ANY sector fails (atomic semantics).
    """
    session = _make_session()
    results: dict[str, dict] = {}
    failures: list[str] = []

    for i, (sector, meta) in enumerate(SECTOR_IDS.items(), 1):
        log.info("[%d/%d] %s (id=%s)", i, len(SECTOR_IDS), sector, meta["id"])
        entry = {"slug": meta["slug"]}
        for key, days in DAYS.items():
            val = fetch_median(session, meta["id"], days)
            if val is None:
                failures.append(f"{sector}:{key}")
            entry[key] = val
            time.sleep(0.8)   # be polite to Screener — at 0.35s we hit 429s
        log.info("      3Y=%s  5Y=%s  10Y=%s",
                 entry.get("median3y"), entry.get("median5y"), entry.get("median10y"))
        results[sector] = entry

    if failures:
        raise RuntimeError(
            f"{len(failures)} median fetches failed — keeping existing file. "
            f"Failures: {', '.join(failures[:8])}{'...' if len(failures) > 8 else ''}"
        )

    return {
        "source": "screener.in /api/company/{id}/chart/ (Index PE + Median Index PE)",
        "scraped_at": datetime.now(IST).isoformat(),
        "note": "Auto-scraped via scrape_medians.py. Values parsed from 'Median Index PE = X'.",
        "medians": results,
    }


def save_atomic(payload: dict) -> None:
    """Backup the old file, then write the new one. Never leaves an empty file."""
    if OUTPUT_FILE.exists():
        BACKUP_FILE.write_text(OUTPUT_FILE.read_text(encoding="utf-8"), encoding="utf-8")
    tmp = OUTPUT_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(OUTPUT_FILE)
    log.info("wrote %s (%d sectors)", OUTPUT_FILE.name, len(payload.get("medians", {})))


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
        stream=sys.stdout,
    )
    dry = "--dry-run" in sys.argv
    log.info("scrape_medians: START  dry_run=%s", dry)
    try:
        payload = scrape_all()
    except RuntimeError as e:
        log.error("SCRAPE FAILED: %s", e)
        log.error("medians_curated.json left UNCHANGED — pipeline will use yesterday's values")
        return 2
    except Exception as e:
        log.exception("unexpected error: %s", e)
        return 3

    if dry:
        print(json.dumps(payload, indent=2))
        log.info("dry-run: not writing file")
        return 0

    save_atomic(payload)
    log.info("scrape_medians: DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())

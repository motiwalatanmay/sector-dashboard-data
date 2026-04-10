"""
pipeline.py — incremental update engine.

Reads existing sector_data.json  →  appends today's fetch  →  recomputes all
stats (medianPE, CAGR, earnTrend, valuationGap …)  →  saves updated JSON.

Design principle: pipeline.py never modifies historical ts entries it didn't
create today.  All stats are derived from ts — no hardcoded look-up tables.
"""
import json
import logging
import statistics
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from config import DATA_FILE, SECTORS, QUARTER_END_MONTHS

IST = timezone(timedelta(hours=5, minutes=30))
log = logging.getLogger(__name__)


# ── Maths helpers ──────────────────────────────────────────────────────────────

def _iqr_clean(values: list[float]) -> list[float]:
    """Remove outliers with 1.5 × IQR rule. Passes through if < 4 points."""
    clean = [v for v in values if v and v > 0]
    if len(clean) < 4:
        return clean
    q1, q3 = statistics.quantiles(clean, n=4)[0], statistics.quantiles(clean, n=4)[2]
    iqr    = q3 - q1
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    return [v for v in clean if lo <= v <= hi]


def _median(values: list[float]) -> Optional[float]:
    clean = _iqr_clean(values)
    return round(statistics.median(clean), 2) if clean else None


def _cagr(start: float, end: float, years: float) -> Optional[float]:
    if not start or not end or start <= 0 or years <= 0:
        return None
    return round((end / start) ** (1.0 / years) - 1, 4)


def _cutoff(years: int) -> str:
    """Returns the YYYY-MM string N years before today. Leap-year safe."""
    now = datetime.now(IST)
    return f"{now.year - years:04d}-{now.month:02d}"


def _years_between(d1: str, d2: str) -> float:
    """Actual span in years between two YYYY-MM date keys."""
    y1, m1 = map(int, d1.split("-"))
    y2, m2 = map(int, d2.split("-"))
    return (y2 - y1) + (m2 - m1) / 12.0


# ── Stats computation ──────────────────────────────────────────────────────────

def compute_stats(ts: list[dict]) -> dict:
    """
    Derives all stats from the full ts array (oldest → newest).
    ts entry shape: {d: "YYYY-MM", pe: float, p: float, e: float}

    Returns stats{} block:
      medianPE, med3, med5, highPE, lowPE,
      cagr3, cagr5, earnTrend, modelMedianPE
    """
    if not ts:
        return {}

    cut3 = _cutoff(3)
    cut5 = _cutoff(5)

    all_pe = [e["pe"] for e in ts if e.get("pe")]
    pe_3y  = [e["pe"] for e in ts if e.get("pe") and e["d"] >= cut3]
    pe_5y  = [e["pe"] for e in ts if e.get("pe") and e["d"] >= cut5]

    earn_all = [e for e in ts if e.get("e") and e["e"] > 0]
    earn_3y  = [e for e in ts if e.get("e") and e["e"] > 0 and e["d"] >= cut3]
    earn_5y  = [e for e in ts if e.get("e") and e["e"] > 0 and e["d"] >= cut5]

    # Earnings CAGR — uses ACTUAL span, not hardcoded years (fixes short-history undercount)
    def _cagr_from(bucket):
        if len(bucket) < 2:
            return None
        span = _years_between(bucket[0]["d"], bucket[-1]["d"])
        if span <= 0:
            return None
        return _cagr(bucket[0]["e"], bucket[-1]["e"], span)

    cagr3 = _cagr_from(earn_3y)
    cagr5 = _cagr_from(earn_5y)

    # YoY earnings trend: latest vs ~12 months ago (leap-year safe)
    earn_trend = None
    if earn_all:
        latest   = earn_all[-1]["e"]
        now_ist  = datetime.now(IST)
        ago_key  = f"{now_ist.year - 1:04d}-{now_ist.month:02d}"
        prior    = [e for e in earn_all if e["d"] <= ago_key]
        if prior and prior[-1]["e"] > 0:
            earn_trend = round((latest - prior[-1]["e"]) / prior[-1]["e"], 4)

    med5 = _median(pe_5y)

    return {
        "medianPE":      _median(all_pe),
        "med3":          _median(pe_3y),
        "med5":          med5,
        "highPE":        round(max(all_pe), 2) if all_pe else None,
        "lowPE":         round(min(all_pe), 2) if all_pe else None,
        "cagr3":         cagr3,
        "cagr5":         cagr5,
        "earnTrend":     earn_trend,
        "modelMedianPE": med5,      # 5Y used as model reference for validation
    }


# ── Current block builder ──────────────────────────────────────────────────────

def build_current(fetch: dict, stats: dict, prev_current: dict | None = None) -> dict:
    """
    Builds the current{} block from today's fetch + computed stats.
    finalMedianPE formula: 0.5×5Y + 0.3×3Y + 0.2×allTime  (matches Screener weighting)

    CURATED MEDIANS PRESERVATION:
    If prev_current contains manually-curated medians (median3y/5y/10y/finalMedianPE),
    those are preserved instead of overwritten with compute_stats output. This protects
    the ground-truth screener-derived medians from being clobbered by the short ts
    history that the pipeline has access to.
    """
    price = fetch.get("price")
    pe    = fetch.get("pe")
    pb    = fetch.get("pb")
    earn  = fetch.get("earn")

    # Prefer curated medians if present in previous state
    prev = prev_current or {}
    med3  = prev.get("median3y")     if prev.get("median3y")     is not None else stats.get("med3")
    med5  = prev.get("median5y")     if prev.get("median5y")     is not None else stats.get("med5")
    med10 = prev.get("median10y")    if prev.get("median10y")    is not None else stats.get("medianPE")

    # finalMedianPE: use curated if present, else weighted blend
    final_med = prev.get("finalMedianPE")
    if final_med is None:
        weights = [(med5, 0.5), (med3, 0.3), (med10, 0.2)]
        if all(m for m, _ in weights):
            final_med = round(sum(m * w for m, w in weights), 2)
        elif med5:
            final_med = med5

    # Upside = (median / current_pe) - 1  →  positive means cheap
    upside3y = round(med3 / pe - 1, 4) if (med3 and pe) else None
    upside5y = round(med5 / pe - 1, 4) if (med5 and pe) else None

    # Valuation gap vs final median
    val_gap = round(pe / final_med - 1, 4) if (pe and final_med) else None

    classification = "fair"
    if val_gap is not None:
        classification = "cheap" if val_gap < -0.20 else "expensive" if val_gap > 0.20 else "fair"

    # Median validation (model vs data-derived)
    mdl  = stats.get("modelMedianPE")
    mdl_med = stats.get("medianPE")
    deviation = round(mdl / mdl_med - 1, 4) if (mdl and mdl_med) else None

    return {
        "price":        price,
        "pe":           pe,
        "earn":         earn,
        "isPB":         fetch.get("isPB", False),
        "pb":           pb,
        "marketPE":     pe,             # dashboard reads marketPE for display
        "pe_source":    fetch.get("pe_source", "nse"),
        "fetched_at":   fetch.get("fetched_at"),
        "median3y":     med3,
        "median5y":     med5,
        "median10y":    med10,
        "finalMedianPE": final_med,
        "upside3y":     upside3y,
        "upside5y":     upside5y,
        "valuationGap": val_gap,
        "classification": classification,
        "medianValidation": {
            "modelMedian":    mdl,
            "screenerMedian": mdl_med,
            "deviation":      deviation,
        },
    }


# ── ts / earnHistory updaters ──────────────────────────────────────────────────

def _upsert_ts(ts: list, entry: dict, freq: str) -> list:
    """
    Inserts or replaces one ts entry by date_key.
    Quarterly indices: only append on quarter-end months (Jan Apr Jul Oct).
    Returns updated sorted list.
    """
    date_key = entry["d"]

    if freq == "quarterly":
        month = int(date_key.split("-")[1])
        if month not in QUARTER_END_MONTHS:
            log.info(f"    ts: skip {date_key} — not a quarter-end month")
            return ts

    for i, row in enumerate(ts):
        if row["d"] == date_key:
            ts[i] = entry
            log.info(f"    ts: updated {date_key}")
            return ts

    ts.append(entry)
    ts.sort(key=lambda x: x["d"])
    log.info(f"    ts: appended {date_key}")
    return ts


def _upsert_earn(earn_hist: list, date_key: str, earn: float) -> list:
    """Inserts or replaces one earnHistory entry. Always monthly."""
    if earn is None:
        return earn_hist
    for i, row in enumerate(earn_hist):
        if row["d"] == date_key:
            earn_hist[i] = {"d": date_key, "e": earn}
            return earn_hist
    earn_hist.append({"d": date_key, "e": earn})
    earn_hist.sort(key=lambda x: x["d"])
    return earn_hist


# ── Main pipeline ──────────────────────────────────────────────────────────────

def run_pipeline(fetch_data: dict | None = None) -> dict:
    """
    Full pipeline:
      1. Load existing sector_data.json (or start fresh if absent).
      2. For each sector in config.SECTORS:
           a. Upsert ts + earnHistory with today's reading.
           b. Recompute all stats from updated ts.
           c. Rebuild current{} block.
      3. Save updated sector_data.json.
      4. Return the final dict (so run_pipeline.py can log a summary).

    fetch_data: output of data_fetch.fetch_all().  Pass None to auto-fetch.
    """
    # Load existing data
    if DATA_FILE.exists():
        with open(DATA_FILE, encoding="utf-8") as f:
            db = json.load(f)
        log.info(f"Loaded {DATA_FILE}  ({DATA_FILE.stat().st_size // 1024} KB)")
    else:
        log.warning(f"{DATA_FILE} not found — run bootstrap.py first to seed historical data")
        db = {"version": "1.0", "sectors": {}}

    # Load scraped medians (screener-sourced, refreshed via scrape_medians.py)
    MEDIANS_FILE = DATA_FILE.parent / "medians_curated.json"
    scraped_medians = {}
    scraped_medians_meta = {}
    if MEDIANS_FILE.exists():
        try:
            with open(MEDIANS_FILE, encoding="utf-8") as f:
                scraped_medians_meta = json.load(f)
            scraped_medians = scraped_medians_meta.get("medians", {})
            log.info(f"Loaded {MEDIANS_FILE.name} — {len(scraped_medians)} sectors "
                     f"with curated medians from screener "
                     f"(scraped_at={scraped_medians_meta.get('scraped_at', '?')})")
        except Exception as e:
            log.warning(f"Could not parse {MEDIANS_FILE}: {e}")

    # Auto-fetch if caller didn't supply data
    if fetch_data is None:
        from data_fetch import fetch_all
        fetch_data = fetch_all()

    now_ist = datetime.now(IST)

    for sector_name, cfg in SECTORS.items():
        log.info(f"\n  {sector_name}")
        fetch = fetch_data.get(sector_name, {})

        if not fetch.get("price"):
            log.warning(f"    no price data — skipping this sector today")
            continue

        date_key = fetch["date_key"]
        freq     = cfg["dataFrequency"]

        # Get or init sector record
        sector = db["sectors"].get(sector_name, {
            "dataFrequency": freq,
            "ts":            [],
            "earnHistory":   [],
            "last4":         [],    # frontend derives this via deriveLast4()
            "stats":         {},
            "current":       {},
        })

        # Build ts entry
        ts_entry = {
            "d":  date_key,
            "pe": fetch["pe"],
            "p":  fetch["price"],
            "e":  fetch["earn"],
        }

        # Upsert arrays
        sector["ts"]          = _upsert_ts(sector.get("ts", []), ts_entry, freq)
        sector["earnHistory"] = _upsert_earn(sector.get("earnHistory", []),
                                              date_key, fetch["earn"])
        sector["last4"]       = []      # always empty — frontend derives it

        # Recompute stats
        stats          = compute_stats(sector["ts"])
        sector["stats"] = stats

        # Build current block — overlay freshly-scraped medians from medians_curated.json
        # onto prior current, then pass to build_current for gap/classification recompute.
        fetch["isPB"]  = cfg["isPB"]
        prev_current   = dict(sector.get("current") or {})
        medians_source = "missing"    # "fresh" | "stale" | "missing"

        if sector_name in scraped_medians:
            sm = scraped_medians[sector_name]
            prev_current["median3y"]  = sm.get("median3y",  prev_current.get("median3y"))
            prev_current["median5y"]  = sm.get("median5y",  prev_current.get("median5y"))
            prev_current["median10y"] = sm.get("median10y", prev_current.get("median10y"))
            # Recompute finalMedianPE from fresh scraped values (0.5×5Y + 0.3×3Y + 0.2×10Y)
            m3, m5, m10 = sm.get("median3y"), sm.get("median5y"), sm.get("median10y")
            if all(x is not None for x in (m3, m5, m10)):
                prev_current["finalMedianPE"] = round(m5 * 0.5 + m3 * 0.3 + m10 * 0.2, 2)

            # Freshness check: was medians_curated.json updated today (IST)?
            scraped_at = (scraped_medians_meta.get("scraped_at") or "")[:10]
            today_key  = now_ist.strftime("%Y-%m-%d")
            medians_source = "fresh" if scraped_at == today_key else "stale"

        sector["current"] = build_current(fetch, stats, prev_current)

        # NSE sanity check: compare Screener 10Y median vs current NSE marketPE.
        # Flag ONLY if deviation > 100% (i.e., live PE is >2x or <0.5x the 10Y
        # median). At this threshold we catch true data-plumbing errors — wrong
        # company_id, decimal-place scale mismatches, Screener returning garbage
        # — WITHOUT firing on legitimate cheap/expensive regimes. Valuation zones
        # (±20%) are handled separately by valuationGap/classification.
        nse_pe  = fetch.get("pe")
        scr_10y = sector["current"].get("median10y")
        nse_mismatch = None
        if nse_pe and scr_10y and scr_10y > 0:
            dev = abs((nse_pe - scr_10y) / scr_10y)
            if dev > 1.0:
                nse_mismatch = round(dev, 4)
                log.warning(
                    "    NSE-Screener PLUMBING CHECK FAILED: pe=%.2f vs scr10y=%.2f → %.0f%% gap (likely wrong company_id or scale error)",
                    nse_pe, scr_10y, dev * 100,
                )

        # Stamp freshness + sanity flags for the dashboard banner
        sector["current"]["mediansSource"] = medians_source
        sector["current"]["nseMismatch"]   = nse_mismatch
        sector["current"]["dataStale"]     = (medians_source != "fresh")

        db["sectors"][sector_name] = sector

        gap = sector["current"].get("valuationGap")
        cls = sector["current"].get("classification", "—")
        log.info(f"    pe={fetch['pe']}  med5={stats.get('med5')}  gap={gap}  → {cls}")

    # Update metadata
    db["version"]      = "1.0"
    db["generated_at"] = now_ist.isoformat()

    # Save
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, separators=(",", ":"))   # compact — keeps file small for GitHub

    kb = DATA_FILE.stat().st_size // 1024
    log.info(f"\nSaved {DATA_FILE}  ({kb} KB)  generated_at={db['generated_at']}")
    return db


# ── Standalone test ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
        stream=sys.stdout,
    )
    run_pipeline()

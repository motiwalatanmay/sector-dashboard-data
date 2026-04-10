"""
data_fetch.py — fetches current price, PE, PB from NSE India.
Primary source : NSE allIndices API (requires session warm-up).
Fallback       : Yahoo Finance for price-only recovery.
Anti-block     : randomised delays between every request.
"""
import time
import random
import logging
from datetime import datetime, timezone, timedelta

import requests

from config import NSE_HEADERS, SECTORS, YF_FALLBACK

IST = timezone(timedelta(hours=5, minutes=30))
log = logging.getLogger(__name__)


# ── NSE Session ────────────────────────────────────────────────────────────────

def _make_nse_session() -> requests.Session:
    """
    Creates a requests.Session with NSE headers and warms it up by hitting
    the homepage first — NSE requires valid cookies before the API works.
    """
    s = requests.Session()
    s.headers.update(NSE_HEADERS)
    try:
        log.info("NSE: warming up session (homepage hit)…")
        s.get("https://www.nseindia.com", timeout=15)
        _wait(3, 6)   # mandatory cool-down after homepage
    except Exception as exc:
        log.warning(f"NSE warm-up warning: {exc}")
    return s


def _wait(lo: float, hi: float) -> None:
    """Random sleep in [lo, hi] seconds — keeps us below NSE's bot threshold."""
    delay = random.uniform(lo, hi)
    log.debug(f"  sleeping {delay:.1f}s")
    time.sleep(delay)


# ── NSE allIndices API ─────────────────────────────────────────────────────────

def _fetch_nse_all_indices(session: requests.Session) -> dict:
    """
    Calls NSE's allIndices endpoint and returns a flat dict:
      { "NIFTY 50": {"price": 22819.6, "pe": 21.57, "pb": 3.65}, ... }

    If the call fails (network, 403, malformed JSON) returns {}.
    NSE returns pe=None for indices where PE is not applicable.
    """
    url = "https://www.nseindia.com/api/allIndices"
    try:
        resp = session.get(url, timeout=15)
        resp.raise_for_status()
        raw  = resp.json().get("data", [])
        out  = {}
        for item in raw:
            name  = (item.get("index") or "").strip()
            price = item.get("last")
            pe    = item.get("pe")
            pb    = item.get("pb")
            if name and price is not None:
                out[name] = {
                    "price": round(float(price), 2),
                    "pe":    round(float(pe), 2)  if pe not in (None, "", "—") else None,
                    "pb":    round(float(pb), 2)  if pb not in (None, "", "—") else None,
                }
        log.info(f"NSE allIndices: got {len(out)} entries")
        return out
    except Exception as exc:
        log.error(f"NSE allIndices failed: {exc}")
        return {}


# ── Yahoo Finance fallback ─────────────────────────────────────────────────────

def _yfinance_price(sector_name: str) -> float | None:
    """Fetch latest close price via yfinance. Returns None if unavailable."""
    sym = YF_FALLBACK.get(sector_name)
    if not sym:
        return None
    try:
        import yfinance as yf
        hist = yf.Ticker(sym).history(period="2d")
        if not hist.empty:
            price = round(float(hist["Close"].iloc[-1]), 2)
            log.info(f"  yfinance fallback {sector_name}: {price}")
            return price
    except Exception as exc:
        log.warning(f"  yfinance failed for {sector_name}: {exc}")
    return None


# ── Master fetch ───────────────────────────────────────────────────────────────

def fetch_all() -> dict:
    """
    Fetches current data for every sector in config.SECTORS.

    Returns:
      {
        "NIFTY 50": {
            "date_key":   "2026-04",      # YYYY-MM, used as ts key
            "price":      22819.6,
            "pe":         21.57,          # None if unavailable
            "pb":         3.65,           # None if not applicable
            "earn":       1057.93,        # derived: price / pe
            "pe_source":  "nse",
            "fetched_at": "2026-04-06T16:15:00+05:30",
        },
        ...
      }

    Sectors where both NSE and yfinance fail will have price=None and are
    logged as warnings. pipeline.py skips them for that day's update.
    """
    now        = datetime.now(IST)
    date_key   = now.strftime("%Y-%m")
    fetched_at = now.isoformat()

    # Step 1: warm NSE session once
    session  = _make_nse_session()
    _wait(2, 4)

    # Step 2: bulk fetch from NSE
    nse_data = _fetch_nse_all_indices(session)
    _wait(4, 8)   # post-bulk cool-down

    result = {}
    for sector_name, cfg in SECTORS.items():
        nse_sym = cfg["nse_symbol"]
        raw     = nse_data.get(nse_sym, {})

        price = raw.get("price")
        pe    = raw.get("pe")
        pb    = raw.get("pb")

        # If NSE didn't return a price, try yfinance (price only)
        if price is None:
            log.warning(f"NSE missing price for '{nse_sym}' — trying yfinance")
            price = _yfinance_price(sector_name)
            _wait(2, 4)

        # Derived earnings: E = P / PE
        earn = None
        if price and pe and pe > 0:
            earn = round(price / pe, 4)

        pe_source = "nse" if pe else ("yfinance_price_only" if price else "unavailable")

        result[sector_name] = {
            "date_key":   date_key,
            "price":      price,
            "pe":         pe,
            "pb":         pb,
            "earn":       earn,
            "pe_source":  pe_source,
            "fetched_at": fetched_at,
        }

        status = f"price={price}  pe={pe}  earn={earn}  src={pe_source}"
        if price:
            log.info(f"  ✓  {sector_name:25s}  {status}")
        else:
            log.warning(f"  ✗  {sector_name:25s}  no data")

        # Per-sector delay — spread the load over a few seconds
        _wait(2, 5)

    fetched_ok = sum(1 for v in result.values() if v["price"])
    log.info(f"fetch_all complete: {fetched_ok}/{len(result)} sectors with data")
    return result


# ── Standalone test ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json, sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
        stream=sys.stdout,
    )
    data = fetch_all()
    print("\n── RESULT ──")
    print(json.dumps(data, indent=2))

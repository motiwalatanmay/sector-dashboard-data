"""
config.py — single source of truth for all pipeline settings.
Edit this file (or set environment variables) before first run.
"""
import os
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR  = Path(__file__).parent
DATA_FILE = BASE_DIR / "sector_data.json"   # pipeline output (also served via GitHub)
LOG_FILE  = BASE_DIR / "pipeline.log"

# ── GitHub ─────────────────────────────────────────────────────────────────────
# Option A: fill in directly below.
# Option B (safer): run  setx GITHUB_TOKEN "ghp_..."  in a terminal, then restart.
GITHUB_TOKEN  = os.getenv("GITHUB_TOKEN",  "")   # Fine-grained PAT, Contents read+write
GITHUB_USER   = os.getenv("GITHUB_USER",   "")   # your GitHub username
GITHUB_REPO   = os.getenv("GITHUB_REPO",   "")   # repo name, e.g. "sector-dashboard-data"
GITHUB_BRANCH = "main"
GITHUB_PATH   = "sector_data.json"               # path inside the repo (root is fine)

# ── NSE request headers ────────────────────────────────────────────────────────
# These mimic a real browser session — do not remove headers.
NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer":         "https://www.nseindia.com/",
    "Origin":          "https://www.nseindia.com",
    "Connection":      "keep-alive",
}

# ── Sector registry ────────────────────────────────────────────────────────────
# nse_symbol    : exact "index" string returned by NSE's allIndices API
# dataFrequency : "monthly" for broad indices, "quarterly" for sector indices
# isPB          : True for banking sectors (they're fairly valued on P/B not P/E)
# quarter_months: which months mark quarter-end for ts appends (quarterly only)
SECTORS = {
    "NIFTY 50": {
        "nse_symbol":    "NIFTY 50",
        "dataFrequency": "monthly",
        "isPB":          False,
    },
    "NIFTY NEXT 50": {
        "nse_symbol":    "NIFTY NEXT 50",
        "dataFrequency": "monthly",
        "isPB":          False,
    },
    "NIFTY SMALLCAP 250": {
        "nse_symbol":    "NIFTY SMALLCAP 250",
        "dataFrequency": "monthly",
        "isPB":          False,
    },
    "NIFTY MICROCAP 250": {
        "nse_symbol":    "NIFTY MICROCAP 250",
        "dataFrequency": "monthly",
        "isPB":          False,
    },
    "NIFTY BANK": {
        "nse_symbol":    "NIFTY BANK",
        "dataFrequency": "quarterly",
        "isPB":          True,
    },
    "NIFTY PSU BANK": {
        "nse_symbol":    "NIFTY PSU BANK",
        "dataFrequency": "quarterly",
        "isPB":          True,
    },
    "NIFTY AUTO": {
        "nse_symbol":    "NIFTY AUTO",
        "dataFrequency": "quarterly",
        "isPB":          False,
    },
    "NIFTY REALTY": {
        "nse_symbol":    "NIFTY REALTY",
        "dataFrequency": "quarterly",
        "isPB":          False,
    },
    "NIFTY IT": {
        "nse_symbol":    "NIFTY IT",
        "dataFrequency": "quarterly",
        "isPB":          False,
    },
    "NIFTY INFRA": {
        "nse_symbol": "NIFTY INFRASTRUCTURE",
        "dataFrequency": "quarterly",
        "isPB":          False,
    },
    "NIFTY PHARMA": {
        "nse_symbol":    "NIFTY PHARMA",
        "dataFrequency": "quarterly",
        "isPB":          False,
    },
    "NIFTY FMCG": {
        "nse_symbol":    "NIFTY FMCG",
        "dataFrequency": "quarterly",
        "isPB":          False,
    },
    "NIFTY METAL": {
        "nse_symbol":    "NIFTY METAL",
        "dataFrequency": "quarterly",
        "isPB":          False,
    },
    "NIFTY ENERGY": {
        "nse_symbol":    "NIFTY ENERGY",
        "dataFrequency": "quarterly",
        "isPB":          False,
    },
}

# Quarter-end months for quarterly ts appends: Jan Apr Jul Oct
QUARTER_END_MONTHS = {1, 4, 7, 10}

# Yahoo Finance fallback symbols (price only — no PE from yfinance)
YF_FALLBACK = {
    "NIFTY 50":      "^NSEI",
    "NIFTY NEXT 50": "^NSMIDCP",
    "NIFTY BANK":    "^NSEBANK",
}

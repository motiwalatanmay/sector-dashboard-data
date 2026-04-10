"""
github_push.py — uploads sector_data.json to GitHub via the Contents API.

No git binary needed. Uses a Personal Access Token (Fine-grained PAT)
with Contents read + write permission on the target repo.
"""
import base64
import logging
import time
from pathlib import Path

import requests

from config import DATA_FILE, GITHUB_TOKEN, GITHUB_USER, GITHUB_REPO, GITHUB_BRANCH, GITHUB_PATH

log = logging.getLogger(__name__)


def push_to_github() -> bool:
    """
    Uploads DATA_FILE to GitHub.  Creates the file if it doesn't exist yet;
    updates it (with the required SHA) if it does.

    Returns True on success, False on any failure.
    """
    if not GITHUB_TOKEN:
        log.error("GITHUB_TOKEN is not set — skipping push.  "
                  "Run: setx GITHUB_TOKEN ghp_your_token_here")
        return False
    if not GITHUB_USER or not GITHUB_REPO:
        log.error("GITHUB_USER or GITHUB_REPO not set in config.py — skipping push.")
        return False

    api_url = (
        f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}"
        f"/contents/{GITHUB_PATH}"
    )
    headers = {
        "Authorization":        f"Bearer {GITHUB_TOKEN}",
        "Accept":               "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    # Read and base64-encode the file
    content_bytes = DATA_FILE.read_bytes()
    encoded       = base64.b64encode(content_bytes).decode()

    # Check if the file already exists (need its SHA to update)
    sha = None
    log.info(f"GitHub: checking existing file at {GITHUB_USER}/{GITHUB_REPO}/{GITHUB_PATH}")
    resp = requests.get(api_url, headers=headers, params={"ref": GITHUB_BRANCH}, timeout=20)

    if resp.status_code == 200:
        sha = resp.json().get("sha")
        log.info(f"GitHub: file exists  sha={sha[:10]}…")
    elif resp.status_code == 404:
        log.info("GitHub: file does not exist yet — will create")
    else:
        log.error(f"GitHub: GET failed  {resp.status_code}  {resp.text[:300]}")
        return False

    # Short pause before the write call
    time.sleep(1)

    # PUT (create or update)
    import json
    from datetime import datetime, timezone, timedelta
    IST    = timezone(timedelta(hours=5, minutes=30))
    commit = f"pipeline: daily update {datetime.now(IST).strftime('%Y-%m-%d %H:%M IST')}"

    payload: dict = {
        "message": commit,
        "content": encoded,
        "branch":  GITHUB_BRANCH,
    }
    if sha:
        payload["sha"] = sha

    resp = requests.put(api_url, headers=headers, json=payload, timeout=60)

    if resp.status_code in (200, 201):
        raw_url = (
            f"https://raw.githubusercontent.com/"
            f"{GITHUB_USER}/{GITHUB_REPO}/{GITHUB_BRANCH}/{GITHUB_PATH}"
        )
        log.info(f"GitHub push OK  →  {raw_url}")
        log.info(f"Set REMOTE_DATA_URL = \"{raw_url}\"  in sector_dashboard_fixed.jsx")
        return True
    else:
        log.error(f"GitHub: PUT failed  {resp.status_code}  {resp.text[:400]}")
        return False


# ── Standalone test ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
        stream=sys.stdout,
    )
    success = push_to_github()
    sys.exit(0 if success else 1)

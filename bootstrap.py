"""
bootstrap.py — ONE-TIME setup script.

Run this ONCE before scheduling the daily pipeline.
It auto-extracts the EMBEDDED_DATA object from sector_dashboard_fixed.jsx
(or sector_dashboard_patched.jsx) and writes it as the initial
sector_data.json that pipeline.py will then update daily.

Usage:
  python bootstrap.py
  python bootstrap.py --force    # overwrite an existing sector_data.json
  python bootstrap.py --jsx path/to/other.jsx

No dict pasting needed. Pure Python, no node dependency.
"""
import argparse
import json
import re
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

IST       = timezone(timedelta(hours=5, minutes=30))
BASE_DIR  = Path(__file__).parent
DATA_FILE = BASE_DIR / "sector_data.json"

# Candidate JSX files, in order of preference
DEFAULT_JSX_CANDIDATES = [
    BASE_DIR / "sector_dashboard_patched.jsx",
    BASE_DIR / "sector_dashboard_fixed.jsx",
]


# ── JSX → JSON extractor ───────────────────────────────────────────────────────

def _find_embedded_block(text: str) -> str:
    """
    Locate the EMBEDDED_DATA object literal in the JSX source and return its
    text (from the opening '{' to the matching '}').  Uses a brace-depth walk
    that respects string literals so inner braces inside strings don't confuse
    the counter.
    """
    marker = "const EMBEDDED_DATA"
    start  = text.find(marker)
    if start < 0:
        raise ValueError("EMBEDDED_DATA not found in JSX")

    i = text.find("{", start)
    if i < 0:
        raise ValueError("no '{' after EMBEDDED_DATA")

    obj_start = i
    depth     = 0
    in_str    = False
    str_ch    = ""
    prev      = ""
    while i < len(text):
        ch = text[i]
        if in_str:
            if ch == str_ch and prev != "\\":
                in_str = False
        else:
            if ch in ('"', "'"):
                in_str = True
                str_ch = ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[obj_start:i + 1]
        prev = ch
        i += 1
    raise ValueError("unbalanced braces in EMBEDDED_DATA")


def _js_object_to_json(js: str) -> str:
    """
    Convert a JS object literal (with unquoted keys) to strict JSON.

    This is intentionally NARROW — it only handles the subset actually used in
    sector_dashboard_fixed.jsx:
      - unquoted identifier keys like  foo:  →  "foo":
      - trailing commas in arrays/objects
      - JS literals true/false/null pass through unchanged (already valid JSON)

    It will NOT handle: template literals, comments, regex, computed keys.
    """
    # 1. Strip /* block comments */ and // line comments (outside strings).
    #    Our JSX embedded data block has no comments, but be defensive.
    def _strip_comments(s: str) -> str:
        out   = []
        i     = 0
        inStr = False
        q     = ""
        while i < len(s):
            c = s[i]
            if inStr:
                out.append(c)
                if c == "\\" and i + 1 < len(s):
                    out.append(s[i + 1])
                    i += 2
                    continue
                if c == q:
                    inStr = False
                i += 1
                continue
            if c in ('"', "'"):
                inStr = True
                q     = c
                out.append(c)
                i += 1
                continue
            if c == "/" and i + 1 < len(s) and s[i + 1] == "/":
                i = s.find("\n", i)
                if i < 0:
                    return "".join(out)
                continue
            if c == "/" and i + 1 < len(s) and s[i + 1] == "*":
                j = s.find("*/", i + 2)
                if j < 0:
                    return "".join(out)
                i = j + 2
                continue
            out.append(c)
            i += 1
        return "".join(out)

    js = _strip_comments(js)

    # 2. Quote unquoted identifier keys: `  foo:` or `{foo:` or `,foo:`
    #    Match a `{` or `,` or start, then optional whitespace, then
    #    an identifier, then `:` — wrap the identifier in quotes.
    def _quote_keys(s: str) -> str:
        pattern = re.compile(
            r'([{,\[]\s*)([A-Za-z_$][A-Za-z0-9_$]*)\s*:'
        )
        return pattern.sub(lambda m: f'{m.group(1)}"{m.group(2)}":', s)

    js = _quote_keys(js)

    # 3. Remove trailing commas before } or ]
    js = re.sub(r",(\s*[}\]])", r"\1", js)

    return js


def extract_embedded_data(jsx_path: Path) -> dict:
    """Parse EMBEDDED_DATA from a JSX file and return a Python dict."""
    text     = jsx_path.read_text(encoding="utf-8")
    obj_text = _find_embedded_block(text)
    json_txt = _js_object_to_json(obj_text)
    return json.loads(json_txt)


# ── Main ───────────────────────────────────────────────────────────────────────

def _locate_jsx(user_path: str | None) -> Path:
    if user_path:
        p = Path(user_path).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"JSX file not found: {p}")
        return p
    for cand in DEFAULT_JSX_CANDIDATES:
        if cand.exists():
            return cand
    raise FileNotFoundError(
        "No JSX found. Looked for: "
        + ", ".join(str(c) for c in DEFAULT_JSX_CANDIDATES)
        + ". Pass --jsx <path> explicitly."
    )


def run(force: bool = False, jsx_path: str | None = None) -> int:
    if DATA_FILE.exists() and not force:
        kb = DATA_FILE.stat().st_size // 1024
        print(f"sector_data.json already exists ({kb} KB) — nothing to do.")
        print("Use  python bootstrap.py --force  to overwrite.")
        return 0

    try:
        jsx = _locate_jsx(jsx_path)
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        return 1

    print(f"Reading EMBEDDED_DATA from {jsx.name} …")
    try:
        data = extract_embedded_data(jsx)
    except Exception as e:
        print(f"ERROR: failed to parse EMBEDDED_DATA: {e}")
        return 1

    if "sectors" not in data:
        print("ERROR: parsed object has no 'sectors' key")
        return 1

    # Stamp with current version + timestamp (pipeline.py will update on next run)
    data["version"]      = "1.0"
    data["generated_at"] = datetime.now(IST).isoformat()

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))

    kb = DATA_FILE.stat().st_size // 1024
    print(f"OK  wrote {DATA_FILE}  ({kb} KB)")
    print(f"    version:      {data['version']}")
    print(f"    generated_at: {data['generated_at']}")
    print(f"    sectors:      {len(data['sectors'])}")
    for name in data["sectors"]:
        s = data["sectors"][name]
        ts_n   = len(s.get("ts", []))
        earn_n = len(s.get("earnHistory", []))
        print(f"      - {name:22s}  ts={ts_n:<3d}  earnHistory={earn_n}")
    print()
    print("Next step: python run_pipeline.py")
    return 0


def _parse_args():
    p = argparse.ArgumentParser(description="Seed sector_data.json from JSX EMBEDDED_DATA")
    p.add_argument("--force", action="store_true", help="overwrite existing sector_data.json")
    p.add_argument("--jsx",   type=str, default=None, help="path to JSX file (default: auto-detect)")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    sys.exit(run(force=args.force, jsx_path=args.jsx))

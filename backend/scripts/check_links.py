"""Link-check every curated resource and record the result (SRS FR-070 / 15.7).

    python scripts/check_links.py            # writes app/seed/resource_verification.json

A resource is marked verified only if a GET (following redirects) returns HTTP 2xx today.
Re-run `python -m app.seed` afterwards so the verified dates reach the database.
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import httpx
import yaml

SEED = Path(__file__).resolve().parents[1] / "app" / "seed"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; RoleReadyLinkChecker/1.0; +resource verification)",
           "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"}


def check(url: str) -> tuple[str, dict]:
    try:
        with httpx.Client(follow_redirects=True, timeout=20, headers=HEADERS) as client:
            with client.stream("GET", url) as resp:
                status = resp.status_code
                final = str(resp.url)
    except httpx.HTTPError as exc:
        return url, {"ok": False, "status": None, "error": type(exc).__name__, "checked_on": date.today().isoformat()}
    return url, {"ok": 200 <= status < 300, "status": status, "final_url": final,
                 "checked_on": date.today().isoformat()}


def main() -> int:
    resources = yaml.safe_load((SEED / "resources.yaml").read_text(encoding="utf-8"))["resources"]
    urls = [r["url"] for r in resources]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = dict(pool.map(check, urls))
    (SEED / "resource_verification.json").write_text(json.dumps(results, indent=2, sort_keys=True) + "\n",
                                                     encoding="utf-8")
    bad = {u: r for u, r in results.items() if not r["ok"]}
    print(f"checked {len(urls)} links: {len(urls) - len(bad)} ok, {len(bad)} not verified")
    for u, r in sorted(bad.items()):
        print(f"  NOT VERIFIED  {r.get('status') or r.get('error')}  {u}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Verifies the Greenhouse/Lever company tokens in config.yaml actually
resolve, and reports whether each board currently has any Dubai/UAE postings.

Run locally: python scripts/check_boards.py
Also runnable via .github/workflows/check-boards.yml (workflow_dispatch) —
useful since some sandboxes/CI environments don't have open internet access
but GitHub Actions runners do.
"""

from __future__ import annotations

import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_config  # noqa: E402

GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
LEVER_URL = "https://api.lever.co/v0/postings/{slug}?mode=json"
UAE_HINTS = ("dubai", "abu dhabi", "sharjah", "uae", "united arab emirates")


def check_greenhouse(token: str) -> str:
    try:
        resp = requests.get(GREENHOUSE_URL.format(token=token), timeout=15)
    except Exception as exc:
        return f"ERROR ({exc})"
    if resp.status_code != 200:
        return f"INVALID (HTTP {resp.status_code})"
    jobs = resp.json().get("jobs", [])
    uae_jobs = [j for j in jobs if any(h in (j.get("location", {}).get("name", "") or "").lower() for h in UAE_HINTS)]
    return f"OK — {len(jobs)} total job(s), {len(uae_jobs)} UAE-located"


def check_lever(slug: str) -> str:
    try:
        resp = requests.get(LEVER_URL.format(slug=slug), timeout=15)
    except Exception as exc:
        return f"ERROR ({exc})"
    if resp.status_code != 200:
        return f"INVALID (HTTP {resp.status_code})"
    postings = resp.json()
    if not isinstance(postings, list):
        return "INVALID (unexpected response shape)"
    uae_jobs = [
        p for p in postings
        if any(h in ((p.get("categories") or {}).get("location", "") or "").lower() for h in UAE_HINTS)
    ]
    return f"OK — {len(postings)} total job(s), {len(uae_jobs)} UAE-located"


def main() -> None:
    config = load_config()
    gh_tokens = config["sources"]["greenhouse"]["companies"]
    lever_slugs = config["sources"]["lever"]["companies"]

    print("=== Greenhouse ===")
    for token in gh_tokens:
        print(f"{token:20s} {check_greenhouse(token)}")

    print("\n=== Lever ===")
    for slug in lever_slugs:
        print(f"{slug:20s} {check_lever(slug)}")


if __name__ == "__main__":
    main()

"""Verifies Greenhouse/Lever company tokens and reports whether each board
currently has any Dubai/UAE postings.

Two modes:

    python scripts/check_boards.py
        Re-verifies the tokens already wired into config.yaml.

    python scripts/check_boards.py --candidates scripts/candidate_boards.txt
        Probes a list of *guessed* tokens to discover new boards worth adding.
        Most guesses 404; only the survivors are worth putting in config.

Also runnable via .github/workflows/check-boards.yml (workflow_dispatch) —
necessary because the dev sandbox has no outbound access to these hosts,
whereas GitHub Actions runners do.
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_config  # noqa: E402

GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
LEVER_URL = "https://api.lever.co/v0/postings/{slug}?mode=json"
UAE_HINTS = ("dubai", "abu dhabi", "sharjah", "uae", "united arab emirates")


class Result:
    """A board probe outcome. `uae` drives the recommendation: a board that
    resolves but has run zero UAE roles for weeks is dead weight in the daily
    run, so it is reported separately from one that is actually hiring here."""

    def __init__(self, ok: bool, total: int = 0, uae: int = 0, note: str = ""):
        self.ok, self.total, self.uae, self.note = ok, total, uae, note

    def __str__(self) -> str:
        if not self.ok:
            return self.note
        return f"OK — {self.total} total job(s), {self.uae} UAE-located"


def _uae_count(locations: list[str]) -> int:
    return sum(1 for loc in locations if any(h in (loc or "").lower() for h in UAE_HINTS))


def check_greenhouse(token: str) -> Result:
    try:
        resp = requests.get(GREENHOUSE_URL.format(token=token), timeout=15)
    except Exception as exc:
        return Result(False, note=f"ERROR ({exc})")
    if resp.status_code != 200:
        return Result(False, note=f"INVALID (HTTP {resp.status_code})")
    try:
        jobs = resp.json().get("jobs", [])
    except Exception:
        return Result(False, note="INVALID (non-JSON response)")
    locations = [(j.get("location") or {}).get("name", "") for j in jobs]
    return Result(True, len(jobs), _uae_count(locations))


def check_lever(slug: str) -> Result:
    try:
        resp = requests.get(LEVER_URL.format(slug=slug), timeout=15)
    except Exception as exc:
        return Result(False, note=f"ERROR ({exc})")
    if resp.status_code != 200:
        return Result(False, note=f"INVALID (HTTP {resp.status_code})")
    try:
        postings = resp.json()
    except Exception:
        return Result(False, note="INVALID (non-JSON response)")
    if not isinstance(postings, list):
        return Result(False, note="INVALID (unexpected response shape)")
    locations = [(p.get("categories") or {}).get("location", "") for p in postings]
    return Result(True, len(postings), _uae_count(locations))


def _probe(entry: tuple[str, str]) -> tuple[str, str, Result]:
    ats, token = entry
    checker = check_greenhouse if ats == "greenhouse" else check_lever
    return ats, token, checker(token)


def _parse_candidates(path: Path) -> list[tuple[str, str]]:
    """Each line is `greenhouse <token>` or `lever <slug>`; # starts a comment."""
    entries: list[tuple[str, str]] = []
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 2 or parts[0] not in ("greenhouse", "lever"):
            print(f"skipping malformed line: {raw!r}", file=sys.stderr)
            continue
        entries.append((parts[0], parts[1]))
    return entries


def _report_candidates(entries: list[tuple[str, str]]) -> None:
    # Probing is almost entirely network wait, so a small thread pool turns
    # a multi-minute serial crawl into a few seconds.
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(_probe, entries))

    hiring_here = [(a, t, r) for a, t, r in results if r.ok and r.uae > 0]
    live_elsewhere = [(a, t, r) for a, t, r in results if r.ok and r.uae == 0]
    dead = [(a, t, r) for a, t, r in results if not r.ok]

    print(f"Probed {len(results)} candidate board(s).\n")

    print(f"=== ADD THESE — board resolves AND has UAE postings ({len(hiring_here)}) ===")
    for ats, token, res in sorted(hiring_here, key=lambda x: -x[2].uae):
        print(f"  {ats:10s} {token:28s} {res}")

    print(f"\n=== Board resolves, but no UAE roles right now ({len(live_elsewhere)}) ===")
    print("    (safe to add — costs one request/day and may list UAE roles later)")
    for ats, token, res in sorted(live_elsewhere, key=lambda x: -x[2].total):
        print(f"  {ats:10s} {token:28s} {res}")

    print(f"\n=== No such board — do not add ({len(dead)}) ===")
    for ats, token, res in dead:
        print(f"  {ats:10s} {token:28s} {res}")


def _report_configured() -> None:
    config = load_config()
    entries = [("greenhouse", t) for t in config["sources"]["greenhouse"]["companies"]]
    entries += [("lever", s) for s in config["sources"]["lever"]["companies"]]

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(_probe, entries))

    for ats, token, res in results:
        print(f"{ats:10s} {token:20s} {res}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidates",
        type=Path,
        help="File of guessed 'greenhouse <token>' / 'lever <slug>' lines to probe.",
    )
    args = parser.parse_args()

    if args.candidates:
        _report_candidates(_parse_candidates(args.candidates))
    else:
        _report_configured()


if __name__ == "__main__":
    main()

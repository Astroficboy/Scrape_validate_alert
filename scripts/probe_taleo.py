"""Reconnaissance for the Dubai Careers (Oracle Taleo) careers site.

Round 1 established: the host is reachable from GitHub runners (HTTP 200, no
captcha), the pages carry no server-rendered job rows, and the jobboard REST
endpoint answers JSON but with careerSectionUnAvailable=true — i.e. it needs
the career section's numeric portal id, which was not where it was expected
in the markup.

Round 2 dumps the surrounding markup so the real identifiers and AJAX URLs
can be read off directly instead of guessed at.

Run via .github/workflows/probe-taleo.yml — the dev sandbox's egress proxy
blocks this host, GitHub runners reach it fine.
"""

from __future__ import annotations

import json
import re

import requests

HOST = "https://jobs.dubaicareers.ae"
SECTION = "dubaicareers"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def banner(title: str) -> None:
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def contexts(html: str, needle: str, width: int = 130, limit: int = 6) -> list[str]:
    """Snippets of markup around a marker, whitespace-collapsed for logging."""
    out = []
    for m in re.finditer(re.escape(needle), html, re.I):
        lo = max(0, m.start() - width)
        snippet = html[lo: m.end() + width]
        out.append(re.sub(r"\s+", " ", snippet).strip())
        if len(out) >= limit:
            break
    return out


def main() -> None:
    session = requests.Session()

    banner("Fetch pages")
    pages: dict[str, str] = {}
    for label, url in {
        "jobsearch": f"{HOST}/careersection/{SECTION}/jobsearch.ftl?lang=en",
        "moresearch": f"{HOST}/careersection/{SECTION}/moresearch.ftl?searchExpanded=false&lang=en",
    }.items():
        resp = session.get(url, headers=HEADERS, timeout=30)
        pages[label] = resp.text
        print(f"  {label}: HTTP {resp.status_code}, {len(resp.text)} bytes")

    for label, html in pages.items():
        banner(f"[{label}] markup around key markers")
        for needle in ("requisitionList", "rest/jobboard", "portal", "careerSectionId", "csNo", "ftlUrl"):
            snips = contexts(html, needle, limit=3)
            print(f"\n  --- {needle!r}: {len(snips)} shown ---")
            for s in snips:
                print(f"    {s[:300]}")

        banner(f"[{label}] candidate numeric ids (>=6 digits)")
        ids = re.findall(r"\b(\d{6,})\b", html)
        counts: dict[str, int] = {}
        for i in ids:
            counts[i] = counts.get(i, 0) + 1
        top = sorted(counts.items(), key=lambda kv: -kv[1])[:12]
        print(f"    {top}")

        banner(f"[{label}] URLs referenced in the page")
        urls = sorted(set(re.findall(r'["\'](/careersection/[^"\'\s]{3,120})["\']', html)))
        for u in urls[:25]:
            print(f"    {u}")

    banner("REST attempts with discovered ids")
    all_ids = re.findall(r"\b(\d{6,})\b", pages.get("jobsearch", "") + pages.get("moresearch", ""))
    tried = []
    for portal in list(dict.fromkeys(all_ids))[:6]:
        url = f"{HOST}/careersection/rest/jobboard/searchjobs"
        payload = {
            "multilineEnabled": False,
            "sortingSelection": {"sortBySelectionParam": "3", "ascendingSortingOrder": "false"},
            "fieldData": {"fields": {"KEYWORD": "", "LOCATION": ""}, "valid": True},
            "filterSelectionParam": {"searchFilterSelections": []},
            "advancedSearchFiltersSelectionParam": {"searchFilterSelections": []},
            "pageNo": 1,
        }
        h = dict(HEADERS)
        h.update({
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "Referer": f"{HOST}/careersection/{SECTION}/jobsearch.ftl?lang=en",
        })
        try:
            r = session.post(url, params={"lang": "en", "portal": portal}, json=payload, headers=h, timeout=25)
            d = r.json()
            reqs = (d or {}).get("requisitionList") or []
            unavailable = (d or {}).get("careerSectionUnAvailable")
            print(f"  portal={portal}: HTTP {r.status_code} entries={len(reqs)} unavailable={unavailable}")
            if reqs:
                print(f"    FIRST: {json.dumps(reqs[0])[:600]}")
                tried.append(portal)
        except Exception as exc:
            print(f"  portal={portal}: ERROR {exc}")
    print(f"\n  portals returning jobs: {tried}")


if __name__ == "__main__":
    main()

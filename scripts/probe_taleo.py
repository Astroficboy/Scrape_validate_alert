"""Reconnaissance for the Dubai Careers (Oracle Taleo) careers site.

Taleo career sections render through FreeMarker (.ftl) templates driven by
session state, so the search URL a human copies out of the address bar is
not fetchable on its own. Newer Taleo instances do expose a JSON REST
endpoint that the page itself calls; this script works out whether this
instance has one, and what shape its responses are, before any scraper is
written against guesses.

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


def probe_html(session: requests.Session) -> str:
    """Fetch the career section landing page and report what came back."""
    banner("1. Landing page (establishes the Taleo session cookie)")
    urls = [
        f"{HOST}/careersection/{SECTION}/jobsearch.ftl?lang=en",
        f"{HOST}/careersection/{SECTION}/moresearch.ftl?searchExpanded=false&lang=en",
        f"{HOST}/careersection/{SECTION}/jobsearch.ftl",
    ]
    html = ""
    for url in urls:
        try:
            resp = session.get(url, headers=HEADERS, timeout=30)
        except Exception as exc:
            print(f"  {url}\n    ERROR {exc}")
            continue
        print(f"  {url}\n    HTTP {resp.status_code}, {len(resp.text)} bytes")
        if resp.status_code == 200 and len(resp.text) > len(html):
            html = resp.text
    print(f"  cookies now: {sorted(session.cookies.keys())}")
    return html


def report_html_signals(html: str) -> None:
    """Look for the identifiers a REST call needs, and for inline job data."""
    banner("2. Signals inside the HTML")
    if not html:
        print("  no HTML captured")
        return

    # Taleo embeds the portal/csrf ids the page's own AJAX calls use.
    patterns = {
        "portal id": r'portal["\']?\s*[:=]\s*["\']?(\d{6,})',
        "csrf token": r'(?:csrf|CSRF)[^"\']{0,20}["\']([A-Za-z0-9_\-]{16,})["\']',
        "requisition ids": r'requisitionId["\']?\s*[:=]\s*["\']?(\d+)',
        "jobdetail links": r'(jobdetail\.ftl\?job=[A-Za-z0-9_\-]+)',
    }
    for label, pat in patterns.items():
        hits = re.findall(pat, html)
        uniq = sorted(set(hits))[:5]
        print(f"  {label:18s} {len(set(hits))} unique {uniq}")

    lowered = html.lower()
    for marker in ("jobsearchresultsform", "requisitionlist", "no matching", "captcha", "javascript is required"):
        print(f"  contains {marker!r}: {marker in lowered}")


def probe_rest(session: requests.Session, portal: str | None) -> None:
    """Try the Taleo jobboard REST endpoint the modern career sections use."""
    banner(f"3. REST endpoint (portal={portal or 'omitted'})")
    url = f"{HOST}/careersection/rest/jobboard/searchjobs"
    params = {"lang": "en"}
    if portal:
        params["portal"] = portal

    payload = {
        "multilineEnabled": False,
        "sortingSelection": {"sortBySelectionParam": "3", "ascendingSortingOrder": "false"},
        "fieldData": {"fields": {"KEYWORD": "", "LOCATION": ""}, "valid": True},
        "filterSelectionParam": {"searchFilterSelections": []},
        "advancedSearchFiltersSelectionParam": {"searchFilterSelections": []},
        "pageNo": 1,
    }
    headers = dict(HEADERS)
    headers["Content-Type"] = "application/json"
    headers["Accept"] = "application/json, text/plain, */*"
    headers["Referer"] = f"{HOST}/careersection/{SECTION}/jobsearch.ftl?lang=en"

    try:
        resp = session.post(url, params=params, json=payload, headers=headers, timeout=30)
    except Exception as exc:
        print(f"  ERROR {exc}")
        return

    print(f"  HTTP {resp.status_code}, {len(resp.text)} bytes, ct={resp.headers.get('content-type')}")
    body = resp.text[:400]
    try:
        data = resp.json()
    except Exception:
        print(f"  non-JSON body: {body!r}")
        return

    reqs = (((data or {}).get("requisitionList")) or [])
    print(f"  requisitionList entries: {len(reqs)}")
    if reqs:
        first = reqs[0]
        print(f"  first entry keys: {sorted(first.keys())}")
        print(f"  sample: {json.dumps(first)[:700]}")
    else:
        print(f"  body head: {json.dumps(data)[:500]}")


def probe_rss(session: requests.Session) -> None:
    """Some Taleo instances publish an RSS feed — far simpler if present."""
    banner("4. RSS / alternate feeds")
    candidates = [
        f"{HOST}/careersection/{SECTION}/rss.ftl?lang=en",
        f"{HOST}/careersection/rss?lang=en",
        f"{HOST}/careersection/{SECTION}/jobsearch.ftl?lang=en&format=rss",
    ]
    for url in candidates:
        try:
            resp = session.get(url, headers=HEADERS, timeout=20)
            head = resp.text[:120].replace("\n", " ")
            print(f"  {url}\n    HTTP {resp.status_code}, {len(resp.text)} bytes, head={head!r}")
        except Exception as exc:
            print(f"  {url}\n    ERROR {exc}")


def main() -> None:
    session = requests.Session()
    html = probe_html(session)
    report_html_signals(html)

    portal_ids = sorted(set(re.findall(r'portal["\']?\s*[:=]\s*["\']?(\d{6,})', html or "")))
    probe_rest(session, None)
    for portal in portal_ids[:2]:
        probe_rest(session, portal)

    probe_rss(session)


if __name__ == "__main__":
    main()

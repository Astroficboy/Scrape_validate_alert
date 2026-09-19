"""Reconnaissance for Naukri Gulf (naukrigulf.com).

Naukri Gulf is the single biggest source of Dubai/UAE AI roles and is not
currently reachable: the system has no scraper for it, and the sanctioned
job-alert-email route needs saved alerts that do not exist yet, so it
contributes zero.

Naukri's sites are React front-ends over a JSON search API rather than
server-rendered listings, and that API is gated on app/system id headers
rather than on a login. This probe works out which endpoint and header
combination this deployment answers, before any scraper is written.

Run via .github/workflows/probe-naukrigulf.yml — the dev sandbox's egress
proxy blocks these hosts, GitHub runners reach them.
"""

from __future__ import annotations

import json

import requests

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
BASE_HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.naukrigulf.com/",
    "Origin": "https://www.naukrigulf.com",
}
# Naukri's APIs identify the calling front-end rather than the user; the
# Gulf property and the India property use different pairs, so try both.
ID_HEADER_SETS = [
    {},
    {"appid": "205", "systemid": "2323"},
    {"appid": "205", "systemid": "godrejgulf"},
    {"appid": "103", "systemid": "103"},
    {"appid": "109", "systemid": "109"},
]

QUERY = {"keyword": "artificial intelligence", "location": "dubai"}


def banner(t: str) -> None:
    print("\n" + "=" * 70 + f"\n{t}\n" + "=" * 70)


def describe_json(data) -> str:
    """Summarise a response without dumping a whole page of JSON."""
    if isinstance(data, dict):
        keys = sorted(data.keys())
        for listkey in ("jobs", "jobDetails", "results", "docs", "jobList"):
            if isinstance(data.get(listkey), list):
                items = data[listkey]
                head = json.dumps(items[0])[:500] if items else "(empty)"
                return f"dict keys={keys[:12]} | {listkey}={len(items)} | first={head}"
        return f"dict keys={keys[:15]} | {json.dumps(data)[:300]}"
    if isinstance(data, list):
        return f"list len={len(data)} | first={json.dumps(data[0])[:400] if data else '(empty)'}"
    return f"{type(data).__name__}: {str(data)[:200]}"


def try_endpoint(session: requests.Session, label: str, url: str, params: dict) -> bool:
    print(f"\n  --- {label} ---")
    print(f"      {url}")
    found = False
    for ids in ID_HEADER_SETS:
        headers = dict(BASE_HEADERS)
        headers.update(ids)
        tag = ids or "(no app/system id)"
        try:
            resp = session.get(url, params=params, headers=headers, timeout=25)
        except Exception as exc:
            print(f"      {tag}: ERROR {exc}")
            continue

        ctype = resp.headers.get("content-type", "")
        line = f"      {tag}: HTTP {resp.status_code}, {len(resp.content)} bytes, ct={ctype.split(';')[0]}"
        if "json" not in ctype:
            print(line + f" | head={resp.text[:100]!r}")
            continue
        try:
            data = resp.json()
        except Exception:
            print(line + " | unparseable JSON")
            continue
        print(line + f"\n        {describe_json(data)}")
        if resp.status_code == 200:
            found = True
    return found


def main() -> None:
    session = requests.Session()

    banner("JSON search endpoints")
    candidates = [
        (
            "spapi/jobapi/searchV2",
            "https://www.naukrigulf.com/spapi/jobapi/searchV2",
            {**QUERY, "pageNo": 1, "pageSize": 50, "srchId": ""},
        ),
        (
            "spapi/jobapi/search",
            "https://www.naukrigulf.com/spapi/jobapi/search",
            {**QUERY, "pageNo": 1, "pageSize": 50},
        ),
        (
            "spapi/jobs/search",
            "https://www.naukrigulf.com/spapi/jobs/search",
            {**QUERY, "pageNo": 1, "pageSize": 50},
        ),
        (
            "api/v2/search",
            "https://www.naukrigulf.com/api/v2/search",
            {**QUERY, "pageNo": 1, "pageSize": 50},
        ),
    ]
    any_ok = False
    for label, url, params in candidates:
        any_ok |= try_endpoint(session, label, url, params)

    banner("Plain HTML search page (fallback route)")
    for url in (
        "https://www.naukrigulf.com/artificial-intelligence-jobs-in-dubai",
        "https://www.naukrigulf.com/jobs-in-dubai?k=artificial%20intelligence",
    ):
        h = dict(BASE_HEADERS)
        h["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        try:
            r = session.get(url, headers=h, timeout=25)
            text = r.text
            print(f"\n  {url}\n    HTTP {r.status_code}, {len(text)} bytes")
            for marker in ("__NEXT_DATA__", "application/ld+json", "JobPosting", "ng-box srp-tuple", "jobTuple"):
                print(f"      contains {marker!r}: {marker in text}")
        except Exception as exc:
            print(f"\n  {url}\n    ERROR {exc}")

    print(f"\n\nAny JSON endpoint returned 200: {any_ok}")


if __name__ == "__main__":
    main()

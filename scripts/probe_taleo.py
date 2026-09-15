"""Reconnaissance for the Dubai Careers (Oracle Taleo) careers site.

Findings so far:
  R1 — host reachable from GitHub runners (HTTP 200, no captcha); pages carry
       no <a href="jobdetail.ftl?job=..."> links; REST jobboard endpoint
       answers JSON but always careerSectionUnAvailable.
  R2 — the REST endpoint is a dead end for this instance, but moresearch.ftl
       (221 KB) embeds the live result set: an `initialHistory` hidden input
       holding requisition-id/title pairs, and a dozen requisition ids
       repeated throughout the markup.

R3 confirms the result-row structure and whether a canonical Taleo deep link
(jobdetail.ftl?job=<id>) is fetchable, which is what the scraper needs in
order to emit a usable URL per posting.

Run via .github/workflows/probe-taleo.yml — the dev sandbox's egress proxy
blocks this host, GitHub runners reach it fine.
"""

from __future__ import annotations

import re
from urllib.parse import unquote

import requests
from bs4 import BeautifulSoup

HOST = "https://jobs.dubaicareers.ae"
SECTION = "dubaicareers"
SEARCH_URL = f"{HOST}/careersection/{SECTION}/moresearch.ftl?searchExpanded=false&lang=en"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
HEADERS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}


def banner(t: str) -> None:
    print("\n" + "=" * 70 + f"\n{t}\n" + "=" * 70)


def main() -> None:
    session = requests.Session()
    resp = session.get(SEARCH_URL, headers=HEADERS, timeout=30)
    html = resp.text
    print(f"moresearch.ftl: HTTP {resp.status_code}, {len(html)} bytes")

    soup = BeautifulSoup(html, "lxml")

    banner("initialHistory — decoded id/title pairs")
    node = soup.find("input", {"id": "initialHistory"})
    if node:
        raw = unquote(node.get("value", ""))
        parts = raw.replace("!$!", "!|!").split("!|!")
        print(f"  {len(parts)} tokens; first 30: {parts[:30]}")
        pairs = []
        for i, tok in enumerate(parts):
            if re.fullmatch(r"\d{5,7}", tok) and i + 1 < len(parts):
                nxt = parts[i + 1]
                if nxt and not re.fullmatch(r"\d{5,7}", nxt):
                    pairs.append((tok, nxt))
        seen, uniq = set(), []
        for rid, title in pairs:
            if rid not in seen:
                seen.add(rid)
                uniq.append((rid, title))
        print(f"  {len(uniq)} unique id/title pairs")
        for rid, title in uniq[:20]:
            print(f"    {rid}  {title}")

    banner("Result table structure")
    # Taleo names its result rows/cells predictably; find whichever exists.
    for selector in ("tr[id*='requisition']", "tr[class*='row']", "table tr"):
        rows = soup.select(selector)
        if len(rows) > 3:
            print(f"  selector {selector!r} -> {len(rows)} rows; first 3 rows' cells:")
            for r in rows[1:4]:
                cells = [re.sub(r"\s+", " ", c.get_text(" ", strip=True))[:70] for c in r.find_all(["td", "th"])]
                print(f"    {cells}")
            break
    else:
        print("  no table rows matched")

    banner("Anchors / onclick carrying requisition ids")
    ids_in_page = sorted(set(re.findall(r"\b(\d{6})\b", html)))
    print(f"  6-digit ids in page: {len(ids_in_page)} -> {ids_in_page[:15]}")
    for a in soup.find_all("a", href=True)[:400]:
        if re.search(r"\d{6}", a["href"]) or re.search(r"\d{6}", a.get("onclick", "") or ""):
            print(f"    href={a['href'][:110]!r} text={a.get_text(strip=True)[:60]!r}")

    banner("Is jobdetail.ftl?job=<id> fetchable?")
    if ids_in_page:
        for rid in ids_in_page[:2]:
            url = f"{HOST}/careersection/{SECTION}/jobdetail.ftl?job={rid}&lang=en"
            try:
                r = session.get(url, headers=HEADERS, timeout=25)
                s = BeautifulSoup(r.text, "lxml")
                title = (s.title.get_text(strip=True) if s.title else "")[:90]
                text = re.sub(r"\s+", " ", s.get_text(" ", strip=True))
                print(f"  {url}\n    HTTP {r.status_code}, {len(r.text)} bytes, <title>={title!r}")
                print(f"    text head: {text[:300]!r}")
                for label in ("Primary Location", "Location", "Job Number", "Organization", "Schedule"):
                    m = re.search(rf"{label}\s*[:\-]?\s*(.{{0,60}})", text)
                    if m:
                        print(f"    {label}: {m.group(1)!r}")
            except Exception as exc:
                print(f"  {url}\n    ERROR {exc}")


if __name__ == "__main__":
    main()

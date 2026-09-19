"""Discovery for Workday-hosted career sites with UAE openings.

Unlike Naukri Gulf and Bayt (both of which silently drop or refuse
datacenter traffic — see scripts/probe_naukrigulf.py), Workday exposes a
genuinely public, unauthenticated JSON search endpoint:

    POST https://<tenant>.<wdN>.myworkdayjobs.com/wday/cxs/<tenant>/<site>/jobs
    {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "..."}

The awkward part is that a tenant's public URL has three unknowns — tenant,
the wdN shard, and the site slug — and guessing all three at once is
hundreds of requests. So this runs in two phases: find which
<tenant>.<wdN> hosts exist at all, then try site slugs only against hosts
that answered. That turns a combinatorial sweep into a cheap one.

Run via .github/workflows/probe-workday.yml — the dev sandbox's egress proxy
blocks these hosts, GitHub runners reach them.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import requests

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}
SHARDS = ("wd1", "wd3", "wd5")
# Slugs Workday customers overwhelmingly pick, plus tenant-derived variants
# generated per tenant below.
COMMON_SITES = (
    "External", "Careers", "careers", "External_Career_Site",
    "ExternalCareerSite", "Global", "Jobs", "en-US",
)
UAE_HINTS = ("dubai", "abu dhabi", "sharjah", "uae", "united arab emirates", "emirates")

# Multinationals with substantial Dubai/Abu Dhabi engineering or regional
# hubs, plus Gulf groups known to run Workday.
TENANTS = [
    "mastercard", "visa", "hsbc", "standardchartered", "citi",
    "siemens", "schneiderelectric", "honeywell", "ge", "emerson",
    "philips", "unilever", "pepsico", "nestle", "mars",
    "dell", "nvidia", "salesforce", "vmware", "workday",
    "pwc", "deloitte", "kpmg", "ey", "accenture",
    "majidalfuttaim", "chalhoub", "aldar", "emaar", "adnoc",
    "emiratesnbd", "mashreq", "dpworld", "aramex", "landmarkgroup",
    "bakerhughes", "halliburton", "slb", "weatherford",
    "thales", "airbus", "boeing", "rolls-royce",
]


def site_candidates(tenant: str) -> list[str]:
    cap = tenant.capitalize()
    return list(dict.fromkeys([
        *COMMON_SITES,
        tenant, cap,
        f"{cap}_Careers", f"{cap}Careers",
        f"{tenant}_careers", f"{cap}_External",
    ]))


def host_alive(args: tuple[str, str]) -> tuple[str, str, bool]:
    tenant, shard = args
    url = f"https://{tenant}.{shard}.myworkdayjobs.com/"
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=10, allow_redirects=True)
        # Workday answers something (200/302/404-with-its-own-chrome) for a
        # real tenant and fails DNS entirely for a made-up one.
        return tenant, shard, r.status_code < 500
    except Exception:
        return tenant, shard, False


def try_site(args: tuple[str, str, str]) -> dict | None:
    tenant, shard, site = args
    url = f"https://{tenant}.{shard}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
    payload = {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "Dubai"}
    try:
        r = requests.post(url, headers=HEADERS, json=payload, timeout=15)
    except Exception:
        return None
    if r.status_code != 200 or "json" not in r.headers.get("content-type", ""):
        return None
    try:
        data = r.json()
    except Exception:
        return None
    postings = data.get("jobPostings")
    if not isinstance(postings, list):
        return None

    uae = [
        p for p in postings
        if any(h in (p.get("locationsText", "") or "").lower() for h in UAE_HINTS)
    ]
    return {
        "tenant": tenant, "shard": shard, "site": site,
        "total": data.get("total", len(postings)),
        "returned": len(postings),
        "uae": len(uae),
        "sample": [
            {"title": p.get("title"), "loc": p.get("locationsText"), "path": p.get("externalPath")}
            for p in (uae or postings)[:3]
        ],
    }


def main() -> None:
    print("=" * 72)
    print("PHASE 1 — which <tenant>.<shard>.myworkdayjobs.com hosts exist?")
    print("=" * 72)
    combos = [(t, s) for t in TENANTS for s in SHARDS]
    with ThreadPoolExecutor(max_workers=24) as pool:
        alive = [r for r in pool.map(host_alive, combos) if r[2]]
    print(f"  {len(alive)} live host(s) out of {len(combos)} probed:")
    for tenant, shard, _ in alive:
        print(f"    {tenant}.{shard}")

    print()
    print("=" * 72)
    print("PHASE 2 — which site slug answers the jobs API?")
    print("=" * 72)
    work = [(t, s, site) for t, s, _ in alive for site in site_candidates(t)]
    print(f"  probing {len(work)} tenant/site combination(s)...\n")
    with ThreadPoolExecutor(max_workers=24) as pool:
        hits = [h for h in pool.map(try_site, work) if h]

    # One site per tenant is enough; prefer whichever surfaced most UAE roles.
    best: dict[str, dict] = {}
    for h in hits:
        cur = best.get(h["tenant"])
        if cur is None or (h["uae"], h["total"]) > (cur["uae"], cur["total"]):
            best[h["tenant"]] = h

    with_uae = sorted([h for h in best.values() if h["uae"]], key=lambda h: -h["uae"])
    without = sorted([h for h in best.values() if not h["uae"]], key=lambda h: -h["total"])

    print(f"=== ADD THESE — API works AND 'Dubai' search returned UAE roles ({len(with_uae)}) ===")
    for h in with_uae:
        print(f"  {h['tenant']}/{h['site']} ({h['shard']}) — total={h['total']}, uae_in_sample={h['uae']}")
        for s in h["sample"]:
            print(f"      {s['title']!r} @ {s['loc']!r}")

    print(f"\n=== API works, no UAE rows in this sample ({len(without)}) ===")
    for h in without:
        print(f"  {h['tenant']}/{h['site']} ({h['shard']}) — total={h['total']}")

    print("\n--- machine-readable ---")
    print(json.dumps(
        [{"tenant": h["tenant"], "shard": h["shard"], "site": h["site"], "uae": h["uae"]}
         for h in sorted(best.values(), key=lambda x: -x["uae"])],
        indent=1,
    ))


if __name__ == "__main__":
    main()

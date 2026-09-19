"""Discovery for Workday-hosted career sites with UAE openings.

Unlike Naukri Gulf and Bayt (both of which silently drop or refuse
datacenter traffic — see scripts/probe_naukrigulf.py), Workday exposes a
genuinely public, unauthenticated JSON search endpoint:

    POST https://<tenant>.<wdN>.myworkdayjobs.com/wday/cxs/<tenant>/<site>/jobs
    {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "..."}

A tenant's public URL has three unknowns — tenant, the wdN shard, and the
site slug. The first attempt here tried to narrow that by checking which
<tenant>.<wdN> hosts "exist" before trying slugs, but myworkdayjobs.com
serves wildcard DNS: every made-up subdomain answers, so that filter passed
all 129 candidates and narrowed nothing. The only signal that actually
distinguishes a real tenant is the CXS endpoint returning job JSON, so this
now goes straight there and leans on concurrency instead. Requests that miss
fail fast with a 404, which keeps even a few thousand combinations cheap.

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
    # Enterprise tech / AI vendors with Gulf regional offices
    "salesforce", "servicenow", "splunk", "paloaltonetworks", "fortinet",
    "crowdstrike", "cloudflare", "mongodb", "elastic", "datadog",
    "vmware", "nokia", "ericsson", "hpe", "lenovo", "ntt", "dxc", "atos",
    "dell", "nvidia", "redhat", "cognizant", "genpact", "publicisgroupe",
    # Payments / banking — heavy Dubai tech hubs
    "mastercard", "visa", "amex", "paypal", "citi", "hsbc",
    "standardchartered", "barclays", "deutschebank", "ubs", "blackrock",
    "fisglobal", "fiserv", "westernunion", "adib", "adcb", "fab",
    "emiratesnbd", "mashreq",
    # Industrial / energy with UAE operations
    "siemens", "siemensenergy", "abb", "schneiderelectric", "honeywell",
    "ge", "gevernova", "emerson", "bakerhughes", "halliburton", "slb",
    "weatherford", "bp", "shell", "totalenergies", "adnoc", "masdar",
    "taqa", "borouge",
    # Aviation / logistics / travel
    "thales", "airbus", "boeing", "rolls-royce", "dhl", "fedex", "ups",
    "maersk", "kuehne-nagel", "agility", "aramex", "dpworld", "etihad",
    "emirates", "flydubai", "dnata",
    # Consulting / professional services
    "pwc", "deloitte", "kpmg", "ey", "accenture", "mckinsey", "bain",
    "bcg", "oliverwyman",
    # FMCG / pharma / retail with regional HQs in Dubai
    "unilever", "pepsico", "cocacola", "nestle", "mars", "mondelez",
    "kraftheinz", "pg", "pfizer", "novartis", "astrazeneca", "gsk",
    "sanofi", "abbott", "jnj",
    # Gulf groups and government-linked entities
    "majidalfuttaim", "alfuttaim", "alshaya", "gmg", "americana",
    "almarai", "agthia", "chalhoub", "landmarkgroup", "aldar", "emaar",
    "jumeirah", "dewa", "tabreed", "yahsat", "g42", "presight", "bayanat",
    "mubadala", "e-and", "du",
]



def site_candidates(tenant: str) -> list[str]:
    cap = tenant.capitalize()
    return list(dict.fromkeys([
        *COMMON_SITES,
        tenant, cap,
        f"{cap}_Careers", f"{cap}Careers",
        f"{tenant}_careers", f"{cap}_External",
    ]))


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
    work = [
        (t, shard, site)
        for t in TENANTS
        for shard in SHARDS
        for site in site_candidates(t)
    ]
    print(f"Probing {len(work)} tenant/shard/site combinations...\n")

    with ThreadPoolExecutor(max_workers=32) as pool:
        hits = [h for h in pool.map(try_site, work) if h]

    # One site per tenant is enough; prefer whichever surfaced most UAE roles.
    best: dict[str, dict] = {}
    for h in hits:
        cur = best.get(h["tenant"])
        if cur is None or (h["uae"], h["total"]) > (cur["uae"], cur["total"]):
            best[h["tenant"]] = h

    with_uae = sorted([h for h in best.values() if h["uae"]], key=lambda h: -h["uae"])
    without = sorted([h for h in best.values() if not h["uae"]], key=lambda h: -h["total"])

    print(f"=== API works AND 'Dubai' search returned UAE roles ({len(with_uae)}) ===")
    for h in with_uae:
        print(f"  {h['tenant']}/{h['site']} ({h['shard']}) — total={h['total']}, uae_in_sample={h['uae']}")
        for sm in h["sample"]:
            print(f"      {sm['title']!r} @ {sm['loc']!r}")

    print(f"\n=== API works, no UAE rows in this sample ({len(without)}) ===")
    for h in without:
        print(f"  {h['tenant']}/{h['site']} ({h['shard']}) — total={h['total']}")

    print("\n--- machine-readable (paste into config.yaml) ---")
    print(json.dumps(
        [{"tenant": h["tenant"], "shard": h["shard"], "site": h["site"], "uae": h["uae"]}
         for h in sorted(best.values(), key=lambda x: -x["uae"])],
        indent=1,
    ))


if __name__ == "__main__":
    main()

"""Workday-hosted career sites (the public CXS JSON search endpoint).

Workday is one of the few large ATS platforms that neither blocks datacenter
traffic nor requires credentials:

    POST https://<tenant>.<shard>.myworkdayjobs.com/wday/cxs/<tenant>/<site>/jobs
    {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "..."}

Every tenant in config.yaml was confirmed answering by
scripts/probe_workday.py — a tenant's public URL has three independent
unknowns (tenant, wdN shard, site slug), so these are observed values, not
guesses, and new ones should be found the same way rather than invented.

Note the query direction. The discovery probe searched for "Dubai" to prove
an endpoint was live, but that is a full-text search, not a location filter,
so it only finds postings whose indexed text happens to contain the city and
badly understates a tenant. Here it runs the other way round: search the
candidate's own role keywords, then keep whatever comes back that is
UAE-located. That surfaces an AI role in Dubai whose text never says
"Dubai", which is the case that matters.
"""

from __future__ import annotations

import logging

import requests

from src.models import JobPosting
from src.scrapers.base import BaseScraper, DEFAULT_HEADERS

logger = logging.getLogger(__name__)

UAE_HINTS = (
    "dubai", "abu dhabi", "sharjah", "ajman", "uae",
    "united arab emirates", "u.a.e",
)


class WorkdayScraper(BaseScraper):
    name = "workday"

    def __init__(self, config: dict):
        super().__init__(config)
        self.src_cfg = config["sources"].get("workday", {})

    def is_enabled(self) -> bool:
        return bool(self.src_cfg.get("enabled", False)) and bool(self.src_cfg.get("tenants"))

    @staticmethod
    def _is_uae(location: str) -> bool:
        loc = (location or "").lower()
        return any(hint in loc for hint in UAE_HINTS)

    def _search(self, tenant: dict, term: str) -> list[dict]:
        name, shard, site = tenant["tenant"], tenant["shard"], tenant["site"]
        url = f"https://{name}.{shard}.myworkdayjobs.com/wday/cxs/{name}/{site}/jobs"
        payload = {
            "appliedFacets": {},
            "limit": self.src_cfg.get("results_per_query", 20),
            "offset": 0,
            "searchText": term,
        }
        headers = {**DEFAULT_HEADERS, "Accept": "application/json", "Content-Type": "application/json"}
        resp = requests.post(url, json=payload, headers=headers, timeout=25)
        resp.raise_for_status()
        postings = (resp.json() or {}).get("jobPostings")
        return postings if isinstance(postings, list) else []

    def _to_posting(self, tenant: dict, item: dict) -> JobPosting | None:
        location = (item.get("locationsText") or "").strip()
        if not self._is_uae(location):
            return None

        path = item.get("externalPath") or ""
        name, shard, site = tenant["tenant"], tenant["shard"], tenant["site"]
        url = f"https://{name}.{shard}.myworkdayjobs.com/{site}{path}"

        title = (item.get("title") or "").strip()
        # bulletFields is Workday's own summary row (req id, category, time
        # type); it is thin, but it is the only free-text the search endpoint
        # returns, and the validator's thin-data cap handles the rest.
        bullets = [str(b) for b in (item.get("bulletFields") or []) if b]
        posted = (item.get("postedOn") or "").strip()
        description = " ".join(filter(None, [title, " ".join(bullets), posted]))

        return JobPosting(
            source="workday",
            title=title,
            company=tenant.get("company") or name.title(),
            location=location,
            url=url,
            description=description,
        )

    def fetch(self) -> list[JobPosting]:
        tenants = self.src_cfg.get("tenants", [])
        terms = self.src_cfg.get("search_terms") or self.config["search"]["queries"]

        jobs: list[JobPosting] = []
        seen_urls: set[str] = set()
        attempts = 0
        failures = 0

        for tenant in tenants:
            for term in terms:
                attempts += 1
                try:
                    items = self._search(tenant, term)
                except Exception:
                    logger.exception(
                        "[workday] %s/%s query %r failed",
                        tenant.get("tenant"), tenant.get("site"), term,
                    )
                    failures += 1
                    continue

                for item in items:
                    posting = self._to_posting(tenant, item)
                    # The same requisition matches several of our search
                    # terms; keep the first and skip the repeats so the
                    # dedup store isn't doing work the scraper can do here.
                    if posting and posting.url not in seen_urls:
                        seen_urls.add(posting.url)
                        jobs.append(posting)

        if attempts and failures == attempts:
            raise RuntimeError(
                "all Workday queries failed — tenants may have moved; "
                "re-run scripts/probe_workday.py to re-verify"
            )

        logger.info(
            "[workday] %d UAE posting(s) from %d tenant(s) over %d quer(ies)",
            len(jobs), len(tenants), attempts,
        )
        return jobs

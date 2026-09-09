"""Broad Google Custom Search discovery — catches roles at companies outside
priority_targets entirely (career pages, ATS boards, Workday postings that
never reach the aggregators), unlike google_watch.py which only looks at a
fixed company list.

Runs one query per (title term x suffix) pair, capped by a shared daily
budget with google_watch.py (see sources.google_search.max_daily_queries and
main.py, which computes how much budget discovery spends before company
watch gets the remainder).
"""

from __future__ import annotations

import logging
import time

import requests

from src.models import JobPosting
from src.scrapers.base import BaseScraper, DEFAULT_HEADERS
from src.scrapers.google_cse_common import ENDPOINT, company_from, is_noise_link, location_from

logger = logging.getLogger(__name__)


class GoogleDiscoveryScraper(BaseScraper):
    name = "google_discovery"

    def __init__(self, config: dict, api_key: str, cse_id: str, query_budget: int | None = None):
        super().__init__(config)
        self.api_key = api_key
        self.cse_id = cse_id
        self.src_cfg = config["sources"]["google_discovery"]
        # None means "use every configured query"; set by main.py once the
        # shared daily budget (sources.google_search.max_daily_queries) is known.
        self.query_budget = query_budget

    def queries(self) -> list[str]:
        """Public: main.py calls this to compute how much of the shared
        Google budget discovery spends, before handing the remainder to
        GoogleWatchScraper."""
        titles = self.config["search"]["queries"]
        suffixes = self.src_cfg.get("suffixes", [])
        queries = [f'"{title}" {suffix}' for title in titles for suffix in suffixes]
        if self.query_budget is not None and len(queries) > self.query_budget:
            queries = queries[: self.query_budget]
        return queries

    def is_enabled(self) -> bool:
        return (
            self.src_cfg.get("enabled", True)
            and bool(self.api_key and self.cse_id)
            and bool(self.queries())
        )

    def fetch(self) -> list[JobPosting]:
        jobs: list[JobPosting] = []
        queries = self.queries()
        results_per_query = self.src_cfg.get("results_per_query", 10)
        date_restrict = self.src_cfg.get("date_restrict", "d3")
        failures = 0

        logger.info("[google_discovery] %d quer(ies) (budget=%s)", len(queries), self.query_budget)

        for query in queries:
            params = {
                "key": self.api_key,
                "cx": self.cse_id,
                "q": query,
                "num": min(results_per_query, 10),
                "dateRestrict": date_restrict,
            }
            try:
                resp = requests.get(ENDPOINT, params=params, headers=DEFAULT_HEADERS, timeout=25)
                if resp.status_code == 429:
                    logger.warning("[google_discovery] daily Google quota exhausted — stopping")
                    break
                resp.raise_for_status()
                data = resp.json()
            except Exception:
                logger.exception("[google_discovery] query %r failed", query)
                failures += 1
                continue

            for item in data.get("items", []):
                link = item.get("link", "")
                if is_noise_link(link):
                    continue
                jobs.append(
                    JobPosting(
                        source="google_discovery",
                        title=item.get("title", "").split(" - ")[0][:140].strip(),
                        company=company_from(item),
                        location=location_from(item) or "Dubai/UAE (targeted search — verify on click-through)",
                        url=link,
                        description=f"{item.get('title', '')} {item.get('snippet', '')}",
                    )
                )
            time.sleep(0.4)  # be polite to the endpoint

        if queries and failures == len(queries):
            raise RuntimeError("all Google discovery queries failed — check GOOGLE_API_KEY/GOOGLE_CSE_ID")

        return jobs

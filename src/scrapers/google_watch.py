"""Google Programmable Search (Custom Search JSON API) company watcher.

Adzuna doesn't cover the UAE and most Tier-1 targets (banks, G42/sovereign AI,
big tech regional offices) run their own careers portals (Workday, in-house)
rather than a scrapable public ATS. Instead of scraping each of those
directly, this issues one targeted Google search per `watch: true` company
in config.yaml's priority_targets, restricted to that company's domain and
biased toward senior AI/engineering roles.

Requires a free Google Custom Search JSON API key (100 queries/day free tier)
and a Programmable Search Engine ID configured to search the entire web —
see README. Costs exactly one query per watched company per run, capped by
sources.google_watch.daily_query_budget.
"""

from __future__ import annotations

import logging

import requests

from src.models import JobPosting
from src.scrapers.base import BaseScraper, DEFAULT_HEADERS
from src.scrapers.google_cse_common import ENDPOINT, is_noise_link

logger = logging.getLogger(__name__)

ROLE_TERMS = '(Lead OR Senior OR Principal OR Staff OR Architect OR "Head of" OR Director)'
DOMAIN_TERMS = '(AI OR "machine learning" OR "artificial intelligence" OR GenAI OR LLM)'
LOCATION_TERMS = '(Dubai OR UAE OR "United Arab Emirates" OR "Abu Dhabi")'


class GoogleWatchScraper(BaseScraper):
    name = "google_watch"

    def __init__(self, config: dict, api_key: str, cse_id: str, query_budget: int | None = None):
        super().__init__(config)
        self.api_key = api_key
        self.cse_id = cse_id
        self.src_cfg = config["sources"]["google_watch"]
        # None means "use sources.google_watch.daily_query_budget as-is";
        # main.py passes an explicit override once it knows how much of the
        # shared sources.google_search.max_daily_queries budget discovery
        # queries left behind.
        self.query_budget = query_budget

    def _watched_companies(self) -> list[tuple[str, str, str]]:
        """Returns (name, domain, tier_key) for every watch:true company,
        truncated to the effective daily query budget."""
        companies: list[tuple[str, str, str]] = []
        for tier_key, tier in self.config.get("priority_targets", {}).items():
            for company in tier.get("companies", []):
                if company.get("watch"):
                    companies.append((company.get("name", ""), company.get("domain", ""), tier_key))

        budget = self.query_budget if self.query_budget is not None else self.src_cfg.get("daily_query_budget", 35)
        if len(companies) > budget:
            logger.warning(
                "[google_watch] %d watched companies exceeds budget=%d — "
                "only searching the first %d", len(companies), budget, budget
            )
        return companies[: max(0, budget)]

    def is_enabled(self) -> bool:
        return (
            self.src_cfg.get("enabled", True)
            and bool(self.api_key and self.cse_id)
            and bool(self._watched_companies())
        )

    def fetch(self) -> list[JobPosting]:
        jobs: list[JobPosting] = []
        companies = self._watched_companies()
        results_per_query = self.src_cfg.get("results_per_query", 10)
        failures = 0

        for name, domain, tier_key in companies:
            site_term = f"site:{domain}" if domain else f'"{name}"'
            query = f"{site_term} jobs {ROLE_TERMS} {DOMAIN_TERMS} {LOCATION_TERMS}"
            params = {
                "key": self.api_key,
                "cx": self.cse_id,
                "q": query,
                "num": min(results_per_query, 10),
            }
            try:
                resp = requests.get(ENDPOINT, params=params, headers=DEFAULT_HEADERS, timeout=20)
                resp.raise_for_status()
                data = resp.json()
            except Exception:
                logger.exception("[google_watch] query for %r failed", name)
                failures += 1
                continue

            for item in data.get("items", []):
                if is_noise_link(item.get("link", "")):
                    continue
                jobs.append(
                    JobPosting(
                        source="google_watch",
                        title=item.get("title", "").strip(),
                        company=name or item.get("displayLink", domain),
                        # Search is location-biased via LOCATION_TERMS but not
                        # guaranteed — flagged here rather than asserted as fact.
                        location="Dubai/UAE (targeted search — verify on click-through)",
                        url=item.get("link", ""),
                        description=item.get("snippet", "") or "",
                    )
                )

        if companies and failures == len(companies):
            raise RuntimeError("all Google Custom Search queries failed — check GOOGLE_API_KEY/GOOGLE_CSE_ID")

        return jobs

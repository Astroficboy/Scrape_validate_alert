"""Adzuna Jobs API — https://developer.adzuna.com/

Official free-tier JSON API with structured salary_min/salary_max fields and
UAE coverage (country code "ae"). This is the primary, most reliable source:
unlike scraping job-board HTML, the response schema is documented and stable.
"""

from __future__ import annotations

import logging

import requests

from src.models import JobPosting
from src.scrapers.base import BaseScraper, DEFAULT_HEADERS

logger = logging.getLogger(__name__)

API_URL = "https://api.adzuna.com/v1/api/jobs/{country}/search/1"


class AdzunaScraper(BaseScraper):
    name = "adzuna"

    def __init__(self, config: dict, app_id: str, app_key: str):
        super().__init__(config)
        self.app_id = app_id
        self.app_key = app_key
        self.src_cfg = config["sources"]["adzuna"]

    def is_enabled(self) -> bool:
        return self.src_cfg.get("enabled", True) and bool(self.app_id and self.app_key)

    def fetch(self) -> list[JobPosting]:
        jobs: list[JobPosting] = []
        country = self.src_cfg.get("country", "ae")
        results_per_query = self.src_cfg.get("results_per_query", 25)
        url = API_URL.format(country=country)
        queries = self.config["search"]["queries"]
        failures = 0

        for query in queries:
            params = {
                "app_id": self.app_id,
                "app_key": self.app_key,
                "results_per_page": results_per_query,
                "what": query,
                "content-type": "application/json",
            }
            try:
                resp = requests.get(url, params=params, headers=DEFAULT_HEADERS, timeout=20)
                resp.raise_for_status()
                data = resp.json()
            except Exception:
                logger.exception("[adzuna] query %r failed", query)
                failures += 1
                continue

            for item in data.get("results", []):
                jobs.append(self._parse(item))

        if queries and failures == len(queries):
            raise RuntimeError("all Adzuna queries failed — check ADZUNA_APP_ID/APP_KEY")

        return jobs

    @staticmethod
    def _parse(item: dict) -> JobPosting:
        location = ""
        loc = item.get("location") or {}
        if isinstance(loc, dict):
            location = loc.get("display_name", "") or ""

        return JobPosting(
            source="adzuna",
            title=item.get("title", "").strip(),
            company=(item.get("company") or {}).get("display_name", "Unknown"),
            location=location,
            url=item.get("redirect_url", ""),
            description=item.get("description", "") or "",
            salary_min=item.get("salary_min"),
            salary_max=item.get("salary_max"),
            salary_currency="AED",  # Adzuna "ae" endpoint returns figures in AED
            posted_date=item.get("created"),
        )

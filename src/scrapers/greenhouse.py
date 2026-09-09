"""Greenhouse public job-board API — no auth needed.

For a company on Greenhouse, https://boards.greenhouse.io/<token> is the
careers page and https://boards-api.greenhouse.io/v1/boards/<token>/jobs
returns its postings as JSON. Populate sources.greenhouse.companies in
config.yaml with the tokens of companies you're targeting (find the token in
their careers page URL).
"""

from __future__ import annotations

import logging

import requests

from src.models import JobPosting
from src.scrapers.base import BaseScraper, DEFAULT_HEADERS

logger = logging.getLogger(__name__)

API_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"


class GreenhouseScraper(BaseScraper):
    name = "greenhouse"

    def __init__(self, config: dict):
        super().__init__(config)
        self.src_cfg = config["sources"]["greenhouse"]

    def is_enabled(self) -> bool:
        return self.src_cfg.get("enabled", True) and bool(self.src_cfg.get("companies"))

    def fetch(self) -> list[JobPosting]:
        jobs: list[JobPosting] = []
        companies = self.src_cfg.get("companies", [])
        failures = 0
        for token in companies:
            try:
                resp = requests.get(API_URL.format(token=token), headers=DEFAULT_HEADERS, timeout=20)
                resp.raise_for_status()
                data = resp.json()
            except Exception:
                logger.exception("[greenhouse] company %r failed", token)
                failures += 1
                continue

            for item in data.get("jobs", []):
                location = (item.get("location") or {}).get("name", "")
                jobs.append(
                    JobPosting(
                        source="greenhouse",
                        title=item.get("title", "").strip(),
                        company=token,
                        location=location,
                        url=item.get("absolute_url", ""),
                        description=item.get("content", "") or "",
                        posted_date=item.get("updated_at"),
                    )
                )

        if companies and failures == len(companies):
            raise RuntimeError("all Greenhouse company lookups failed")

        return jobs

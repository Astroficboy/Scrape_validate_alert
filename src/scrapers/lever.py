"""Lever public postings API — no auth needed.

For a company on Lever, https://jobs.lever.co/<slug> is the careers page and
https://api.lever.co/v0/postings/<slug>?mode=json returns postings as JSON.
Populate sources.lever.companies in config.yaml with slugs you're targeting.
"""

from __future__ import annotations

import logging

import requests

from src.models import JobPosting
from src.scrapers.base import BaseScraper, DEFAULT_HEADERS

logger = logging.getLogger(__name__)

API_URL = "https://api.lever.co/v0/postings/{slug}?mode=json"


class LeverScraper(BaseScraper):
    name = "lever"

    def __init__(self, config: dict):
        super().__init__(config)
        self.src_cfg = config["sources"]["lever"]

    def is_enabled(self) -> bool:
        return self.src_cfg.get("enabled", True) and bool(self.src_cfg.get("companies"))

    def fetch(self) -> list[JobPosting]:
        jobs: list[JobPosting] = []
        companies = self.src_cfg.get("companies", [])
        failures = 0
        for slug in companies:
            try:
                resp = requests.get(API_URL.format(slug=slug), headers=DEFAULT_HEADERS, timeout=20)
                resp.raise_for_status()
                data = resp.json()
            except Exception:
                logger.exception("[lever] company %r failed", slug)
                failures += 1
                continue

            for item in data:
                categories = item.get("categories") or {}
                location = categories.get("location", "")
                salary = item.get("salaryDescription") or ""
                jobs.append(
                    JobPosting(
                        source="lever",
                        title=item.get("text", "").strip(),
                        company=slug,
                        location=location,
                        url=item.get("hostedUrl", ""),
                        description=(item.get("descriptionPlain") or item.get("description") or "") + " " + salary,
                        posted_date=str(item.get("createdAt", "")),
                    )
                )

        if companies and failures == len(companies):
            raise RuntimeError("all Lever company lookups failed")

        return jobs

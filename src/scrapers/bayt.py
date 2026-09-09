"""Best-effort HTML scraper for Bayt.com's Dubai/UAE job listings.

Bayt is not a documented API — this parses public search-result pages with
BeautifulSoup, using several fallback selector strategies since Bayt's markup
has changed multiple times historically. Treat this source as supplementary
and fragile: if it starts returning 0 results, Bayt's HTML has likely changed
and the selectors below need updating (inspect a saved copy of the search
page and adjust `_CARD_SELECTORS` / `_FIELD_SELECTORS`).
"""

from __future__ import annotations

import logging
import urllib.parse

import requests
from bs4 import BeautifulSoup

from src.models import JobPosting
from src.scrapers.base import BaseScraper, DEFAULT_HEADERS

logger = logging.getLogger(__name__)

# Multiple candidate selectors tried in order; the first that yields results wins.
_CARD_SELECTORS = ["li[data-js-job]", "div.has-pointer-d[data-job-id]", "li.has-pointer-d"]
_TITLE_SELECTORS = ["h2", "h3", "a.jb-title"]
_COMPANY_SELECTORS = ["b.jb-company", "span.jb-company", "div.t-nowrap.p10l.p10r"]
_LOCATION_SELECTORS = ["span.jb-loc", "div.t-mute.t-small"]


class BaytScraper(BaseScraper):
    name = "bayt"

    def __init__(self, config: dict):
        super().__init__(config)
        self.src_cfg = config["sources"]["bayt"]

    def is_enabled(self) -> bool:
        return self.src_cfg.get("enabled", True)

    def fetch(self) -> list[JobPosting]:
        jobs: list[JobPosting] = []
        base_url = self.src_cfg.get("search_url", "https://www.bayt.com/en/uae/jobs/")
        queries = self.config["search"]["queries"]
        failures = 0

        for query in queries:
            url = f"{base_url}?{urllib.parse.urlencode({'q': query})}"
            try:
                resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=20)
                resp.raise_for_status()
            except Exception:
                logger.exception("[bayt] query %r failed", query)
                failures += 1
                continue

            soup = BeautifulSoup(resp.text, "lxml")
            cards = self._select_first_match(soup, _CARD_SELECTORS)
            if not cards:
                logger.warning(
                    "[bayt] no job cards matched known selectors for query %r "
                    "— Bayt's markup may have changed", query
                )
                continue

            for card in cards:
                job = self._parse_card(card, url)
                if job is not None:
                    jobs.append(job)

        if queries and failures == len(queries):
            raise RuntimeError("all Bayt requests failed — site may be blocking scraping or is unreachable")

        return jobs

    @staticmethod
    def _select_first_match(soup: BeautifulSoup, selectors: list[str]):
        for sel in selectors:
            found = soup.select(sel)
            if found:
                return found
        return []

    def _parse_card(self, card, fallback_url: str) -> JobPosting | None:
        title_el = self._first(card, _TITLE_SELECTORS)
        if title_el is None:
            return None

        link_el = title_el.find("a") if title_el.name != "a" else title_el
        link_el = link_el or card.find("a", href=True)
        url = link_el["href"] if link_el and link_el.has_attr("href") else fallback_url
        if url.startswith("/"):
            url = f"https://www.bayt.com{url}"

        company_el = self._first(card, _COMPANY_SELECTORS)
        location_el = self._first(card, _LOCATION_SELECTORS)

        return JobPosting(
            source="bayt",
            title=title_el.get_text(strip=True),
            company=company_el.get_text(strip=True) if company_el else "Unknown",
            location=location_el.get_text(strip=True) if location_el else "UAE",
            url=url,
        )

    @staticmethod
    def _first(card, selectors: list[str]):
        for sel in selectors:
            el = card.select_one(sel)
            if el is not None:
                return el
        return None

"""Common scraper interface. Every scraper is independent and must fail soft:
an exception here is caught by the orchestrator and logged, never crashes
the whole run — one broken source should not stop alerts from other sources."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from src.models import JobPosting

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


class BaseScraper(ABC):
    name: str = "base"

    def __init__(self, config: dict):
        self.config = config
        self.had_error = False

    @abstractmethod
    def is_enabled(self) -> bool:
        ...

    @abstractmethod
    def fetch(self) -> list[JobPosting]:
        ...

    def safe_fetch(self) -> list[JobPosting]:
        self.had_error = False
        if not self.is_enabled():
            logger.info("[%s] skipped (disabled or missing credentials)", self.name)
            return []
        try:
            jobs = self.fetch()
            logger.info("[%s] fetched %d job(s)", self.name, len(jobs))
            return jobs
        except Exception:
            logger.exception("[%s] fetch failed", self.name)
            self.had_error = True
            return []

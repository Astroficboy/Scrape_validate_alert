"""Data model shared by every scraper, the validator, and the notifiers."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


@dataclass
class JobPosting:
    source: str
    title: str
    company: str
    location: str
    url: str
    description: str = ""
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    posted_date: str | None = None

    # Populated by the validator; not set by scrapers.
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    salary_note: str = ""

    @property
    def job_id(self) -> str:
        """Stable dedup key: same URL (or source+title+company as fallback)."""
        basis = self.url or f"{self.source}:{self.company}:{self.title}"
        return hashlib.sha256(basis.strip().lower().encode("utf-8")).hexdigest()[:20]

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "url": self.url,
            "salary_min": self.salary_min,
            "salary_max": self.salary_max,
            "salary_currency": self.salary_currency,
            "posted_date": self.posted_date,
            "score": round(self.score, 1),
            "reasons": self.reasons,
            "salary_note": self.salary_note,
        }

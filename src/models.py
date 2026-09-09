"""Data model shared by every scraper, the validator, and the notifiers."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Query params that are pure tracking noise and would otherwise make the same
# posting hash differently depending on which link/referrer it arrived via.
_TRACKING_PREFIXES = ("utm_", "trk", "ref", "src", "originalsubdomain", "lipi")
_TRACKING_EXACT = {
    "refid", "trackingid", "ebp", "midtoken", "midsig", "trkemail",
    "otptoken", "from", "position", "pagenum", "alid", "gclid", "fbclid",
    "campaignid", "s_kwcid", "sourceid", "vjs", "tk", "xkcb", "xpse", "jsa",
}
# Params that genuinely identify the posting and must survive cleaning.
_KEEP_PARAMS = {"jk", "currentjobid", "jobid", "id", "job_id", "gh_jid", "lid"}


def canonical_url(url: str) -> str:
    """Strips tracking junk so the same posting reached via different links
    (e.g. two different alert emails) always dedupes to the same job_id."""
    if not url:
        return url
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()

    kept = []
    for key, value in parse_qsl(parts.query, keep_blank_values=False):
        lowered = key.lower()
        if lowered in _KEEP_PARAMS:
            kept.append((key, value))
        elif lowered in _TRACKING_EXACT or any(lowered.startswith(p) for p in _TRACKING_PREFIXES):
            continue
        else:
            kept.append((key, value))

    netloc = parts.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parts.path.rstrip("/") or "/"

    return urlunsplit(("https", netloc, path, urlencode(sorted(kept)), ""))


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
        """Stable dedup key: canonicalized URL (or source+title+company as
        fallback), so the same posting reached via different tracking links
        or different sources still dedupes to one entry."""
        basis = canonical_url(self.url) or f"{self.source}:{self.company}:{self.title}"
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

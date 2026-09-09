"""Shared helpers for Google Custom Search JSON API scrapers
(google_watch.py, google_discovery.py)."""

from __future__ import annotations

ENDPOINT = "https://www.googleapis.com/customsearch/v1"

# Domains that are never an actual job posting — filters CSE noise.
SKIP_DOMAINS = (
    "wikipedia.org", "youtube.com", "reddit.com", "quora.com",
    "coursera.org", "udemy.com", "medium.com", "facebook.com",
    "twitter.com", "x.com", "pinterest.com", "slideshare.net",
)


def is_noise_link(url: str) -> bool:
    return any(domain in url for domain in SKIP_DOMAINS)


def company_from(result: dict) -> str:
    meta = result.get("pagemap", {}) or {}
    for posting in meta.get("jobposting", []) or []:
        name = posting.get("hiringorganization") or posting.get("name")
        if name:
            return str(name)[:80]
    for org in meta.get("organization", []) or []:
        if org.get("name"):
            return str(org["name"])[:80]
    display = result.get("displayLink", "")
    host = display.replace("www.", "").split(".")[0]
    return host.title() if host else ""


def location_from(result: dict) -> str:
    for posting in (result.get("pagemap", {}) or {}).get("jobposting", []) or []:
        loc = posting.get("joblocation") or posting.get("addresslocality")
        if loc:
            return str(loc)[:80]
    return ""

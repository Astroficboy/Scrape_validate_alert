"""Dubai Careers — the Government of Dubai's Oracle Taleo careers portal.

Why this needs its own scraper rather than a generic HTML parse:

Taleo career sections are session-driven FreeMarker apps. The search URL a
human copies out of the address bar is not fetchable on its own, the result
rows carry no <a href="jobdetail.ftl?job=..."> anchors, and this instance's
JSON jobboard endpoint answers `careerSectionUnAvailable` for every portal
id in the page (all verified by scripts/probe_taleo.py against the live
site).

What does work: the search page embeds its whole result set in a hidden
`initialHistory` input, as a delimited token stream. Per posting it reads:

    <reqId> <title> <reqId> <title> <reqId>x5 <employerId>
    <employer> <category> <dd/mm/yyyy> Apply ...

which lines up with the rendered table header, "Requisition ID : Employer :
Job Category : Job Posting". Parsing anchors on the date token rather than
on fixed offsets, so a change in how many times Taleo repeats the id does
not silently shift which field is read as the employer.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import unquote

import requests
from bs4 import BeautifulSoup

from src.models import JobPosting
from src.scrapers.base import BaseScraper, DEFAULT_HEADERS

logger = logging.getLogger(__name__)

HOST = "https://jobs.dubaicareers.ae"
SECTION = "dubaicareers"
DEFAULT_SEARCH_URL = f"{HOST}/careersection/{SECTION}/moresearch.ftl?searchExpanded=false&lang=en"
JOB_URL = f"{HOST}/careersection/{SECTION}/jobdetail.ftl?job={{req_id}}&lang=en"

# Taleo escapes "$" as %24 inside the history value; both act as separators.
_TOKEN_SPLIT = "!|!"
_DOLLAR_SEP = "!$!"
_REQ_ID_RE = re.compile(r"^\d{5,7}$")
_DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
# How far past a requisition id the posting date may sit before we treat the
# record as unparseable rather than reading some unrelated token as employer.
_DATE_LOOKAHEAD = 24


class DubaiCareersScraper(BaseScraper):
    name = "dubai_careers"

    def __init__(self, config: dict):
        super().__init__(config)
        self.src_cfg = config["sources"].get("dubai_careers", {})

    def is_enabled(self) -> bool:
        return bool(self.src_cfg.get("enabled", False))

    def fetch(self) -> list[JobPosting]:
        url = self.src_cfg.get("search_url") or DEFAULT_SEARCH_URL
        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=30)
        resp.raise_for_status()

        tokens = self._history_tokens(resp.text)
        if not tokens:
            # A layout change here is silent otherwise: HTTP 200, zero jobs,
            # indistinguishable from "nothing posted today".
            raise RuntimeError(
                "Dubai Careers: no initialHistory payload found — the Taleo "
                "page layout has probably changed; re-run scripts/probe_taleo.py"
            )

        jobs = [self._to_posting(rec) for rec in self._records(tokens)]
        logger.info("[dubai_careers] parsed %d posting(s) from the result set", len(jobs))
        return jobs

    @staticmethod
    def _history_tokens(html: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        node = soup.find("input", {"id": "initialHistory"})
        if not node or not node.get("value"):
            return []
        raw = unquote(node["value"]).replace(_DOLLAR_SEP, _TOKEN_SPLIT)
        return [t.strip() for t in raw.split(_TOKEN_SPLIT)]

    @classmethod
    def _records(cls, tokens: list[str]) -> list[dict]:
        """One record per distinct requisition id, in page order."""
        records: list[dict] = []
        seen: set[str] = set()

        for idx, token in enumerate(tokens):
            if not _REQ_ID_RE.match(token) or token in seen:
                continue

            title = tokens[idx + 1] if idx + 1 < len(tokens) else ""
            # A bare id followed by another id is one of Taleo's repeats, not
            # the record head — the head is the one followed by the title.
            if not title or _REQ_ID_RE.match(title):
                continue

            employer, category, posted = "", "", ""
            for j in range(idx + 2, min(idx + _DATE_LOOKAHEAD, len(tokens))):
                if _DATE_RE.match(tokens[j]):
                    posted = tokens[j]
                    employer = tokens[j - 2] if j >= 2 else ""
                    category = tokens[j - 1] if j >= 1 else ""
                    break

            seen.add(token)
            records.append({
                "req_id": token,
                "title": title,
                "employer": employer,
                "category": category,
                "posted": posted,
            })

        return records

    @staticmethod
    def _to_posting(rec: dict) -> JobPosting:
        bits = [rec["title"]]
        if rec["category"]:
            bits.append(f"{rec['category']} role")
        if rec["employer"]:
            bits.append(f"at {rec['employer']}")
        if rec["posted"]:
            bits.append(f"(posted {rec['posted']})")
        bits.append("Government of Dubai entity — full description on the posting page.")

        return JobPosting(
            source="dubai_careers",
            title=rec["title"],
            # Employer is the specific Dubai Government entity (e.g. RTA,
            # Dubai Municipality); fall back to the portal owner when Taleo
            # omits it rather than leaving the company blank.
            company=rec["employer"] or "Government of Dubai",
            # Not a guess: this portal only carries Government of Dubai roles,
            # all based in the emirate. Stating it plainly matters because the
            # validator hard-gates on location and would otherwise drop every
            # posting from this source.
            location="Dubai, UAE",
            url=JOB_URL.format(req_id=rec["req_id"]),
            description=" ".join(bits),
        )

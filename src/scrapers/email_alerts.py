"""Reads job-alert emails over IMAP and extracts the postings.

LinkedIn, Indeed, Naukrigulf, GulfTalent and Bayt all run bot detection —
direct scraping gets an IP blocked within days and risks the account. The
legitimate route: create a saved search with a **daily email alert** on each
board (scoped to the target titles + Dubai/UAE location), pointed at a
dedicated inbox, and read that inbox over IMAP. No scraping, no ToS risk —
each board hands over exactly what its own search already filtered for.

Setup is manual (see README) — this only reads what's already in the inbox.
"""

from __future__ import annotations

import email
import imaplib
import logging
import re
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header

from bs4 import BeautifulSoup

from src.models import JobPosting
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

# URL shapes that identify an actual posting link (not a footer/unsubscribe link).
JOB_URL_PATTERNS = [
    (re.compile(r"linkedin\.com/(comm/)?jobs/view/", re.I), "LinkedIn"),
    (re.compile(r"indeed\.[a-z.]+/(rc/clk|viewjob|job/|pagead)", re.I), "Indeed"),
    (re.compile(r"naukrigulf\.com/[a-z0-9\-]+-jobs?", re.I), "Naukri Gulf"),
    (re.compile(r"naukrigulf\.com/job-listings", re.I), "Naukri Gulf"),
    (re.compile(r"gulftalent\.com/[a-z\-]+/jobs?/", re.I), "GulfTalent"),
    (re.compile(r"bayt\.com/[a-z]{2}/[a-z\-]+/jobs/", re.I), "Bayt"),
    (re.compile(r"monstergulf\.com/job-", re.I), "Monster Gulf"),
    (re.compile(r"glassdoor\.[a-z.]+/(job-listing|partner/jobListing)", re.I), "Glassdoor"),
]

_NOISE = re.compile(
    r"unsubscribe|manage (your )?(alert|preference|email)|privacy|help cent|"
    r"view (in|on) browser|download the app|see all jobs|settings|"
    r"^\s*(apply|view job|save|see more|show more)\s*$",
    re.I,
)

_UNKNOWN_LOCATION = "Dubai/UAE (from job-alert email — board-side filtered, unparsed)"


def _decode(value: str) -> str:
    try:
        return str(make_header(decode_header(value or "")))
    except Exception:
        return value or ""


def _html_parts(msg) -> list[str]:
    out = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    out.append(payload.decode(charset, errors="replace"))
    else:
        payload = msg.get_payload(decode=True)
        if payload and msg.get_content_type() == "text/html":
            charset = msg.get_content_charset() or "utf-8"
            out.append(payload.decode(charset, errors="replace"))
    return out


def _classify(url: str) -> str | None:
    for pattern, board in JOB_URL_PATTERNS:
        if pattern.search(url):
            return board
    return None


def _job_links_in(node) -> int:
    return sum(1 for a in node.find_all("a", href=True) if _classify(a["href"]))


def _context_for(anchor) -> tuple[str, str]:
    """Company and location text from the tightest block around this one job.

    Alert emails nest each posting in its own cell or div. Walk up only while
    the ancestor still contains exactly one job link — the moment it swallows
    a sibling posting, we've gone too far and stop.
    """
    node, best = anchor, anchor
    for _ in range(5):
        parent = node.parent
        if parent is None or parent.name in ("body", "html", "[document]"):
            break
        if _job_links_in(parent) != 1:
            break
        best, node = parent, parent

    blob = best.get_text("  ", strip=True)[:400]
    lines = [ln.strip() for ln in re.split(r"\s{2,}|·|•|\||\n", blob) if ln.strip()]

    company, location = "", ""
    title_l = anchor.get_text(" ", strip=True).lower()
    for line in lines:
        if line.lower() == title_l or _NOISE.search(line):
            continue
        if re.search(r"dubai|abu dhabi|sharjah|uae|emirates|remote", line, re.I):
            location = location or line[:80]
        elif not company and 2 < len(line) < 70:
            company = line
    return company, location or _UNKNOWN_LOCATION


def _extract(html: str, default_board: str) -> list[JobPosting]:
    soup = BeautifulSoup(html, "lxml")
    jobs, seen = [], set()

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        board = _classify(href)
        if not board:
            continue

        title = anchor.get_text(" ", strip=True)
        if not title or len(title) < 4 or _NOISE.search(title):
            continue
        if len(title) > 140:
            continue

        key = (title.lower(), href.split("?")[0])
        if key in seen:
            continue
        seen.add(key)

        company, location = _context_for(anchor)
        jobs.append(
            JobPosting(
                source=board or default_board,
                title=title,
                company=company,
                location=location,
                url=href,
                description=f"{title} {company} {location}",
            )
        )
    return jobs


class EmailAlertsScraper(BaseScraper):
    name = "email_alerts"

    def __init__(self, config: dict, imap_user: str, imap_password: str):
        super().__init__(config)
        self.imap_user = imap_user
        self.imap_password = imap_password
        self.src_cfg = config["sources"]["email_alerts"]

    def is_enabled(self) -> bool:
        return self.src_cfg.get("enabled", True) and bool(self.imap_user and self.imap_password)

    def fetch(self) -> list[JobPosting]:
        host = self.src_cfg.get("imap_host", "imap.gmail.com")
        mailbox = self.src_cfg.get("mailbox", "INBOX")
        lookback = int(self.src_cfg.get("lookback_hours", 26))
        senders = self.src_cfg.get("senders", {})
        mark_as_read = self.src_cfg.get("mark_as_read", True)

        since = (datetime.now(timezone.utc) - timedelta(hours=lookback)).strftime("%d-%b-%Y")
        cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback)
        collected: list[JobPosting] = []

        try:
            conn = imaplib.IMAP4_SSL(host)
            conn.login(self.imap_user, self.imap_password)
            conn.select(mailbox)
        except Exception as exc:
            raise RuntimeError(f"IMAP connection/login failed: {exc}") from exc

        try:
            status, data = conn.search(None, f'(SINCE "{since}")')
            if status != "OK":
                raise RuntimeError("IMAP search failed")

            uids = data[0].split()
            logger.info("[email_alerts] %d message(s) since %s", len(uids), since)

            for uid in uids:
                status, raw = conn.fetch(uid, "(RFC822)")
                if status != "OK" or not raw or not raw[0]:
                    continue

                msg = email.message_from_bytes(raw[0][1])
                sender = _decode(msg.get("From", "")).lower()

                board = None
                for domain, name in senders.items():
                    if domain.lower() in sender:
                        board = name
                        break
                if not board:
                    continue

                try:
                    sent = email.utils.parsedate_to_datetime(msg.get("Date"))
                    if sent.tzinfo is None:
                        sent = sent.replace(tzinfo=timezone.utc)
                    if sent < cutoff:
                        continue
                except Exception:
                    pass

                found = []
                for html in _html_parts(msg):
                    found.extend(_extract(html, board))

                if found:
                    subject = _decode(msg.get("Subject", ""))[:70]
                    logger.info("[email_alerts] %s: %d from %r", board, len(found), subject)
                    collected.extend(found)

                if mark_as_read:
                    conn.store(uid, "+FLAGS", "\\Seen")
        finally:
            try:
                conn.close()
                conn.logout()
            except Exception:
                pass

        return collected

"""Entry point: scrape -> validate/score -> dedup -> notify (email + WhatsApp).

Run daily by .github/workflows/daily-job-alert.yml. Designed to run headless
with no UI: all output is logs plus the two notification channels. Each
scraper and each notifier fails independently and is logged rather than
raising, so one broken source/channel never blocks the rest of the run.
"""

from __future__ import annotations

import logging
import sys

from src.config import SEEN_JOBS_PATH, Secrets, load_config
from src.digest import (
    build_email_html,
    build_empty_whatsapp_text,
    build_failure_alert,
    build_whatsapp_text,
)
from src.logging_setup import configure_logging
from src.models import JobPosting
from src.notifiers.email_notifier import send_email
from src.notifiers.whatsapp_notifier import send_whatsapp
from src.scrapers.adzuna import AdzunaScraper
from src.scrapers.bayt import BaytScraper
from src.scrapers.dubai_careers import DubaiCareersScraper
from src.scrapers.workday import WorkdayScraper
from src.scrapers.email_alerts import EmailAlertsScraper
from src.scrapers.google_discovery import GoogleDiscoveryScraper
from src.scrapers.google_watch import GoogleWatchScraper
from src.scrapers.greenhouse import GreenhouseScraper
from src.scrapers.lever import LeverScraper
from src.store import SeenJobsStore
from src.validator import validate_and_score

logger = logging.getLogger(__name__)


def run() -> int:
    configure_logging()
    config = load_config()
    secrets = Secrets(config)

    # Google Custom Search has one daily query budget shared between broad
    # discovery and the priority-company watch: discovery spends first, the
    # watch gets whatever's left (see config.yaml sources.google_search).
    total_google_budget = config["sources"]["google_search"]["max_daily_queries"]
    discovery_scraper = GoogleDiscoveryScraper(
        config, secrets.google_api_key, secrets.google_cse_id, query_budget=total_google_budget
    )
    discovery_spend = len(discovery_scraper.queries()) if discovery_scraper.is_enabled() else 0
    watch_budget = max(0, total_google_budget - discovery_spend)

    scrapers = [
        EmailAlertsScraper(config, secrets.imap_user, secrets.imap_password),
        AdzunaScraper(config, secrets.adzuna_app_id, secrets.adzuna_app_key),
        GreenhouseScraper(config),
        LeverScraper(config),
        DubaiCareersScraper(config),
        WorkdayScraper(config),
        BaytScraper(config),
        discovery_scraper,
        GoogleWatchScraper(config, secrets.google_api_key, secrets.google_cse_id, query_budget=watch_budget),
    ]

    all_jobs: list[JobPosting] = []
    failed_sources: list[str] = []

    for scraper in scrapers:
        jobs = scraper.safe_fetch()
        all_jobs.extend(jobs)
        if scraper.had_error:
            failed_sources.append(scraper.name)

    logger.info("Total raw jobs collected: %d", len(all_jobs))

    validated = validate_and_score(all_jobs, config)
    logger.info("Jobs passing filters/scoring: %d", len(validated))

    store = SeenJobsStore(SEEN_JOBS_PATH)
    new_jobs = store.filter_new(validated)
    logger.info("New (not previously alerted) jobs: %d", len(new_jobs))

    digest_cfg = config["digest"]

    # --- Email ---
    if new_jobs or digest_cfg.get("notify_email_on_empty", True):
        subject, html = build_email_html(new_jobs, config)
        send_email(secrets, subject, html)

    # --- WhatsApp ---
    if new_jobs:
        text = build_whatsapp_text(new_jobs, config)
        send_whatsapp(secrets, text)
    elif digest_cfg.get("notify_whatsapp_on_empty", False):
        send_whatsapp(secrets, build_empty_whatsapp_text())

    # --- Failure self-alert: never fail silently ---
    if failed_sources and digest_cfg.get("notify_on_source_failure", True):
        subject, html = build_failure_alert(failed_sources)
        send_email(secrets, subject, html)

    store.mark_seen(new_jobs)
    pruned = store.prune()
    if pruned:
        logger.info("Pruned %d stale entries from seen-jobs store", pruned)
    store.save()

    return 0


if __name__ == "__main__":
    sys.exit(run())

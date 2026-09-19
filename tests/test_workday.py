"""Tests for the Workday CXS scraper.

Fixtures mirror real response shapes seen from the live endpoint via
scripts/probe_workday.py, including the differing `locationsText` formats
each tenant uses ("AE - Dubai, United Arab Emirates", "Dubai",
"UAE - Remote", "United Arab Emirates, Dubai, Dubai").
"""

import pytest

from src.scrapers.workday import WorkdayScraper

_TENANT = {"tenant": "visa", "shard": "wd5", "site": "visa", "company": "Visa"}


@pytest.fixture
def scraper(config):
    config = dict(config)
    config["sources"] = dict(config["sources"])
    config["sources"]["workday"] = {
        "enabled": True,
        "search_terms": ["artificial intelligence"],
        "tenants": [_TENANT],
    }
    return WorkdayScraper(config)


def _item(**over):
    base = {
        "title": "Senior Data Scientist",
        "externalPath": "/job/Dubai/Senior-Data-Scientist_JR123",
        "locationsText": "AE - Dubai, United Arab Emirates",
        "postedOn": "Posted 2 Days Ago",
        "bulletFields": ["JR123", "Full time"],
    }
    base.update(over)
    return base


@pytest.mark.parametrize("location", [
    "AE - Dubai, United Arab Emirates",
    "Dubai",
    "UAE - Remote",
    "United Arab Emirates, Dubai, Dubai",
    "Abu Dhabi",
    "Sharjah, U.A.E",
])
def test_uae_location_formats_are_all_recognised(scraper, location):
    assert scraper._to_posting(_TENANT, _item(locationsText=location)) is not None


@pytest.mark.parametrize("location", [
    "London, United Kingdom",
    "Austin, TX",
    "Singapore",
    "",
])
def test_non_uae_locations_are_dropped(scraper, location):
    assert scraper._to_posting(_TENANT, _item(locationsText=location)) is None


def test_posting_url_is_built_from_tenant_shard_site_and_path(scraper):
    job = scraper._to_posting(_TENANT, _item())
    assert job.url == (
        "https://visa.wd5.myworkdayjobs.com/visa/job/Dubai/Senior-Data-Scientist_JR123"
    )


def test_company_uses_the_configured_display_name(scraper):
    assert scraper._to_posting(_TENANT, _item()).company == "Visa"


def test_company_falls_back_to_the_tenant_when_unnamed(scraper):
    bare = {"tenant": "maersk", "shard": "wd3", "site": "Maersk_Careers"}
    assert scraper._to_posting(bare, _item()).company == "Maersk"


def test_description_carries_bullets_and_posted_date(scraper):
    job = scraper._to_posting(_TENANT, _item())
    assert "JR123" in job.description
    assert "Full time" in job.description
    assert "Posted 2 Days Ago" in job.description


def test_repeated_requisition_across_search_terms_is_emitted_once(scraper, monkeypatch):
    # The same job matches several of our terms; the scraper should not rely
    # on the dedup store to clean that up.
    scraper.src_cfg["search_terms"] = ["artificial intelligence", "machine learning"]
    monkeypatch.setattr(scraper, "_search", lambda tenant, term: [_item()])
    jobs = scraper.fetch()
    assert len(jobs) == 1


def test_every_query_failing_raises_so_the_source_reports_unhealthy(scraper, monkeypatch):
    def boom(tenant, term):
        raise RuntimeError("network down")

    monkeypatch.setattr(scraper, "_search", boom)
    with pytest.raises(RuntimeError, match="all Workday queries failed"):
        scraper.fetch()


def test_partial_failure_still_returns_what_worked(scraper, monkeypatch):
    scraper.src_cfg["search_terms"] = ["a", "b"]
    calls = {"n": 0}

    def flaky(tenant, term):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        return [_item()]

    monkeypatch.setattr(scraper, "_search", flaky)
    assert len(scraper.fetch()) == 1


def test_disabled_without_tenants(config):
    config = dict(config)
    config["sources"] = {**config["sources"], "workday": {"enabled": True, "tenants": []}}
    assert WorkdayScraper(config).is_enabled() is False

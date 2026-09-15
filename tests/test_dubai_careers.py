"""Parser tests for the Dubai Careers (Taleo) scraper.

The token fixtures below are the real stream observed from the live site via
scripts/probe_taleo.py, not invented shapes — the whole point of this parser
is to survive Taleo's odd repetition, so testing against a hand-tidied
version would test the wrong thing.
"""

from urllib.parse import quote

from src.scrapers.dubai_careers import DubaiCareersScraper

# Exactly as observed: id and title repeat, then the id repeats five more
# times, then employerId, employer, category, posting date, action labels.
_JOB_1 = [
    "163393", "Customer Happiness Officer",
    "163393", "Customer Happiness Officer",
    "163393", "163393", "163393", "163393", "163393",
    "26002346", "Mohammed Bin Rashid Al Maktoum Library", "Administration",
    "15/09/2026",
    "Apply", "Apply for this position (Customer Happiness Officer)",
    "163393", "true", "Re-apply", "Re-apply for this job", "163393",
    "false", "false",
]
_JOB_2 = [
    "165637", "Information Security Specialist",
    "165637", "Information Security Specialist",
    "165637", "165637", "165637",
    "26002999", "Dubai Electricity and Water Authority", "Engineering",
    "11/09/2026",
    "Apply", "Apply for this position", "165637", "false",
]
_HEADER = [
    "ftlx0", "jobsearch_processSearchInitialHistory", "requisitionListInterface",
    "listRequisition", "rlPager", "false", "false", "false",
]


def _html(tokens: list[str]) -> str:
    value = quote("!|!".join(tokens))
    return f'<html><body><input type="hidden" id="initialHistory" value="{value}" /></body></html>'


def _records(tokens: list[str]) -> list[dict]:
    return DubaiCareersScraper._records(DubaiCareersScraper._history_tokens(_html(tokens)))


def test_parses_id_title_employer_category_and_date():
    (rec,) = _records(_HEADER + _JOB_1)
    assert rec["req_id"] == "163393"
    assert rec["title"] == "Customer Happiness Officer"
    assert rec["employer"] == "Mohammed Bin Rashid Al Maktoum Library"
    assert rec["category"] == "Administration"
    assert rec["posted"] == "15/09/2026"


def test_each_posting_appears_once_despite_repeated_ids():
    recs = _records(_HEADER + _JOB_1 + _JOB_2)
    assert [r["req_id"] for r in recs] == ["163393", "165637"]


def test_employer_is_anchored_on_the_date_not_a_fixed_offset():
    # Job 2 repeats its id three times rather than five. Fixed offsets would
    # read the wrong tokens here; anchoring on the date keeps it correct.
    recs = _records(_HEADER + _JOB_2)
    assert recs[0]["employer"] == "Dubai Electricity and Water Authority"
    assert recs[0]["category"] == "Engineering"


def test_record_without_a_date_is_skipped_rather_than_mis_parsed():
    truncated = ["165999", "Some Role", "165999", "165999", "26002000", "Some Entity"]
    (rec,) = _records(_HEADER + truncated)
    # Better to emit the posting with blank employer than to guess wrongly.
    assert rec["title"] == "Some Role"
    assert rec["employer"] == ""
    assert rec["posted"] == ""


def test_posting_has_a_real_url_and_dubai_location():
    (rec,) = _records(_HEADER + _JOB_1)
    job = DubaiCareersScraper._to_posting(rec)
    assert job.url == (
        "https://jobs.dubaicareers.ae/careersection/dubaicareers/"
        "jobdetail.ftl?job=163393&lang=en"
    )
    assert job.location == "Dubai, UAE"
    assert job.company == "Mohammed Bin Rashid Al Maktoum Library"
    assert job.source == "dubai_careers"


def test_missing_employer_falls_back_to_the_portal_owner():
    job = DubaiCareersScraper._to_posting(
        {"req_id": "1", "title": "T", "employer": "", "category": "", "posted": ""}
    )
    assert job.company == "Government of Dubai"


def test_missing_history_payload_yields_no_records():
    assert DubaiCareersScraper._history_tokens("<html><body>nothing</body></html>") == []

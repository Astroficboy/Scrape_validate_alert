"""Regression tests for domain-keyword matching.

`domain_keywords` contains "ai". With plain substring matching that fires
inside maintenance / available / email / detail / training, which passes
essentially any posting and makes the domain gate a no-op — invisible while
every source was a tech board, glaring against a general-purpose government
careers portal.
"""

from src.models import JobPosting
from src.validator import _contains_topic, validate_and_score


def test_ai_does_not_fire_inside_ordinary_words():
    for text in (
        "laboratory equipment maintenance technician",
        "email the details to the training team",
        "rooms available on request",
    ):
        assert not _contains_topic(text, ["ai"]), text


def test_ai_still_matches_when_it_is_a_real_word():
    for text in ("Lead AI Engineer", "ai-driven platform", "work on AI."):
        assert _contains_topic(text, ["ai"]), text


def test_prefix_style_multiword_needles_keep_substring_matching():
    # "data scien" is deliberately written as a prefix so it catches both.
    assert _contains_topic("senior data scientist", ["data scien"])
    assert _contains_topic("head of data science", ["data scien"])


def test_spaced_needle_still_matches():
    assert _contains_topic("strong ml background", [" ml "])


def test_single_token_needle_needs_a_word_boundary():
    assert _contains_topic("platform engineering role", ["engineering"])
    assert not _contains_topic("bioengineeringx", ["engineering"])


def test_government_maintenance_job_is_rejected_end_to_end(config):
    # Would previously pass: "Manager" gives seniority, and "ai" inside
    # "maintenance" satisfied the domain gate.
    jobs = [
        JobPosting(
            source="dubai_careers",
            title="Manager - Laboratory Equipment Maintenance",
            company="Dubai Municipality",
            location="Dubai, UAE",
            url="https://jobs.dubaicareers.ae/careersection/dubaicareers/jobdetail.ftl?job=1&lang=en",
            description="Oversees maintenance of laboratory equipment. Available across sites.",
        )
    ]
    assert validate_and_score(jobs, config) == []


def test_genuine_government_ai_job_still_passes(config):
    jobs = [
        JobPosting(
            source="dubai_careers",
            title="Head of AI and Data Science",
            company="Digital Dubai",
            location="Dubai, UAE",
            url="https://jobs.dubaicareers.ae/careersection/dubaicareers/jobdetail.ftl?job=2&lang=en",
            description="Lead AI, machine learning and LLM initiatives in Python across government services.",
        )
    ]
    assert len(validate_and_score(jobs, config)) == 1

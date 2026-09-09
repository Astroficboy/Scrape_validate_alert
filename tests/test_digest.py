from src.digest import build_email_html, build_empty_whatsapp_text, build_whatsapp_text
from src.models import JobPosting


def _job() -> JobPosting:
    job = JobPosting(
        source="adzuna",
        title="Principal AI Engineer",
        company="Acme AI",
        location="Dubai, UAE",
        url="https://example.com/job/1",
    )
    job.score = 82.5
    job.salary_note = "~48,000 AED/month disclosed"
    job.reasons = ["Senior-level title", "AI/engineering domain match"]
    return job


def test_whatsapp_text_contains_job_details(config):
    text = build_whatsapp_text([_job()], config)
    assert "Principal AI Engineer" in text
    assert "Acme AI" in text
    assert "https://example.com/job/1" in text
    assert "48,000 AED" in text


def test_whatsapp_text_respects_max_jobs_cap(config):
    jobs = [_job() for _ in range(15)]
    for i, j in enumerate(jobs):
        j.url = f"https://example.com/job/{i}"
    text = build_whatsapp_text(jobs, config)
    cap = config["digest"]["max_jobs_whatsapp"]
    assert f"+{15 - cap} more" in text


def test_empty_whatsapp_text_mentions_no_new_roles():
    text = build_empty_whatsapp_text()
    assert "No new matching roles" in text


def test_email_html_contains_job_link_and_subject(config):
    subject, html = build_email_html([_job()], config)
    assert "1 new match" in subject
    assert "https://example.com/job/1" in html
    assert "Principal AI Engineer" in html


def test_email_html_empty_state(config):
    subject, html = build_email_html([], config)
    assert "0 new match" in subject
    assert "No new matching roles" in html

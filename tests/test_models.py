from src.models import JobPosting, canonical_url


def test_canonical_url_strips_tracking_params():
    dirty = "https://www.example.com/jobs/123/?utm_source=linkedin&utm_campaign=x&ref=share"
    assert canonical_url(dirty) == "https://example.com/jobs/123"


def test_canonical_url_keeps_identifying_params():
    url = "https://boards.greenhouse.io/apply?gh_jid=98765&utm_source=x"
    assert "gh_jid=98765" in canonical_url(url)
    assert "utm_source" not in canonical_url(url)


def test_canonical_url_strips_www_and_trailing_slash():
    assert canonical_url("https://www.example.com/jobs/1/") == "https://example.com/jobs/1"


def test_same_posting_different_tracking_links_dedupe_to_same_job_id():
    a = JobPosting(
        source="linkedin", title="Lead AI Engineer", company="Acme", location="Dubai",
        url="https://www.linkedin.com/jobs/view/12345?utm_source=email&trkEmail=x",
    )
    b = JobPosting(
        source="google_discovery", title="Lead AI Engineer", company="Acme", location="Dubai",
        url="https://linkedin.com/jobs/view/12345?refId=abc&trackingId=def",
    )
    assert a.job_id == b.job_id


def test_different_postings_get_different_job_ids():
    a = JobPosting(source="test", title="A", company="X", location="Dubai", url="https://example.com/jobs/1")
    b = JobPosting(source="test", title="B", company="X", location="Dubai", url="https://example.com/jobs/2")
    assert a.job_id != b.job_id

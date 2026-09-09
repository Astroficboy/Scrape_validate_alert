from src.models import JobPosting
from src.validator import validate_and_score


def _job(**overrides) -> JobPosting:
    defaults = dict(
        source="test",
        title="Lead AI Engineer",
        company="Acme AI",
        location="Dubai, UAE",
        url="https://example.com/job/1",
        description="Build agentic AI and LLM/RAG systems in Python on GCP.",
    )
    defaults.update(overrides)
    return JobPosting(**defaults)


def test_matching_senior_ai_dubai_job_passes(config):
    jobs = [_job()]
    result = validate_and_score(jobs, config)
    assert len(result) == 1
    assert result[0].score > 0


def test_junior_role_is_excluded(config):
    jobs = [_job(title="Junior AI Engineer", description="Great entry level opportunity, internship possible.")]
    result = validate_and_score(jobs, config)
    assert result == []


def test_non_senior_title_is_excluded(config):
    jobs = [_job(title="AI Engineer")]  # no seniority keyword
    result = validate_and_score(jobs, config)
    assert result == []


def test_non_uae_location_is_excluded(config):
    jobs = [_job(location="London, UK")]
    result = validate_and_score(jobs, config)
    assert result == []


def test_non_domain_job_is_excluded(config):
    jobs = [_job(title="Lead Sales Manager", description="Manage a sales team and hit revenue targets.")]
    result = validate_and_score(jobs, config)
    assert result == []


def test_low_disclosed_salary_excluded(config):
    jobs = [_job(salary_min=15000, salary_max=15000, salary_currency="AED")]
    result = validate_and_score(jobs, config)
    assert result == []


def test_high_disclosed_monthly_salary_boosts_score(config):
    low = _job(url="https://example.com/job/low")
    high = _job(url="https://example.com/job/high", salary_min=50000, salary_max=55000, salary_currency="AED")
    result = validate_and_score([low, high], config)
    scores = {j.url: j.score for j in result}
    assert scores["https://example.com/job/high"] > scores["https://example.com/job/low"]


def test_annual_salary_is_detected_and_converted(config):
    # 600,000 AED/year ~= 50,000 AED/month -> should pass, not be excluded as "too low".
    jobs = [_job(salary_min=600000, salary_max=600000, salary_currency="AED")]
    result = validate_and_score(jobs, config)
    assert len(result) == 1
    assert "50,000" in result[0].salary_note or "49," in result[0].salary_note


def test_results_sorted_by_score_descending(config):
    strong = _job(
        url="https://example.com/job/strong",
        description="Agentic AI, generative AI, RAG, LLM, LangChain, MLOps, Python, GCP, Databricks.",
    )
    weak = _job(url="https://example.com/job/weak", description="AI engineering role.")
    result = validate_and_score([weak, strong], config)
    assert [j.url for j in result] == [
        "https://example.com/job/strong",
        "https://example.com/job/weak",
    ]

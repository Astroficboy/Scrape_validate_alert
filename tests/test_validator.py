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


def test_priority_target_boosts_score_over_unknown_company(config):
    tier1 = _job(url="https://example.com/job/g42", company="G42", description="AI role at G42, Abu Dhabi.")
    unknown = _job(url="https://example.com/job/unknown", company="Some Random Startup")
    result = validate_and_score([unknown, tier1], config)
    scores = {j.url: j.score for j in result}
    assert scores["https://example.com/job/g42"] > scores["https://example.com/job/unknown"]
    tier1_job = next(j for j in result if j.company == "G42")
    assert any("Priority target" in r for r in tier1_job.reasons)


def test_deprioritised_company_scores_lower_than_unknown(config):
    services_firm = _job(url="https://example.com/job/wipro", company="Wipro")
    unknown = _job(url="https://example.com/job/unknown2", company="Some Random Startup")
    result = validate_and_score([services_firm, unknown], config)
    scores = {j.url: j.score for j in result}
    # Wipro may or may not clear min_score_to_alert once the -25 tier penalty
    # applies; if it's still present, it must rank below the unknown company.
    if "https://example.com/job/wipro" in scores:
        assert scores["https://example.com/job/wipro"] < scores["https://example.com/job/unknown2"]


def test_years_within_ai_experience_boosts_score(config):
    within = _job(
        url="https://example.com/job/within",
        description="Build agentic AI systems. Requires 4+ years of experience in ML.",
    )
    beyond = _job(
        url="https://example.com/job/beyond",
        description="Build agentic AI systems. Requires 20+ years of experience in ML.",
    )
    result = validate_and_score([beyond, within], config)
    scores = {j.url: j.score for j in result if j.url in {"https://example.com/job/within", "https://example.com/job/beyond"}}
    # "beyond" (20y, past max_years_tolerated=12) may or may not clear the
    # score threshold; if present, it must rank below "within" (4y, matches
    # ai_years=5).
    assert "https://example.com/job/within" in scores
    if "https://example.com/job/beyond" in scores:
        assert scores["https://example.com/job/within"] > scores["https://example.com/job/beyond"]


def test_unstated_years_requirement_does_not_penalise(config):
    jobs = [_job(description="Build agentic AI and LLM/RAG systems in Python on GCP. No years stated.")]
    result = validate_and_score(jobs, config)
    assert len(result) == 1
    assert not any("out of range" in r for r in result[0].reasons)


def test_thin_data_job_is_capped_below_full_length_equivalent(config):
    # Same skill/location signal, but one description is padded well past
    # the 60-char thin-data threshold with more matched skill keywords.
    thin = _job(url="https://example.com/job/thin", description="AI GCP Python")
    rich = _job(
        url="https://example.com/job/rich",
        description=(
            "Agentic AI, generative AI, RAG, LLM, LangChain, MLOps, Python, "
            "GCP, Databricks, PyTorch, TensorFlow, semantic search, prompt "
            "engineering, and OpenAI integration for a production platform."
        ),
    )
    result = validate_and_score([thin, rich], config)
    scores = {j.url: j.score for j in result}
    assert scores["https://example.com/job/thin"] <= 72
    assert scores["https://example.com/job/rich"] > scores["https://example.com/job/thin"]


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

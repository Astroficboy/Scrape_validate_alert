"""Filters and scores scraped jobs against the candidate's target profile:
Dubai/UAE location, senior AI/engineering roles, and (where disclosed) a
45,000 AED/month salary floor — see config/config.yaml for the tunable
keyword lists and weights this module reads.
"""

from __future__ import annotations

import re

from src.models import JobPosting


def _contains_any(text: str, needles: list[str]) -> bool:
    text = text.lower()
    return any(needle.lower() in text for needle in needles)


def _normalize_salary_to_aed(amount: float, currency: str | None, fx_table: dict) -> float | None:
    currency = (currency or "AED").upper()
    rate = fx_table.get(currency)
    if rate is None:
        return None
    return amount * rate


def _matches_location(location: str, locations: list[str]) -> bool:
    location_l = location.lower()
    return any(loc.lower() in location_l for loc in locations)


def _score_skills(text: str, skill_weights: dict[str, int]) -> tuple[float, list[str]]:
    text_l = text.lower()
    total = 0
    max_possible = sum(skill_weights.values())
    hit_skills = []
    for skill, weight in skill_weights.items():
        if skill in text_l:
            total += weight
            hit_skills.append(skill)
    normalized = (total / max_possible) * 100 if max_possible else 0
    return normalized, hit_skills


def build_priority_index(priority_targets: dict) -> list[tuple[str, str, float, str]]:
    """Flattens config.yaml's priority_targets tiers into (name, domain,
    bonus, tier_key) tuples for fast lookup per job."""
    index: list[tuple[str, str, float, str]] = []
    for tier_key, tier in (priority_targets or {}).items():
        bonus = tier.get("bonus", 0)
        for company in tier.get("companies", []):
            name = (company.get("name") or "").strip().lower()
            domain = (company.get("domain") or "").strip().lower()
            if name or domain:
                index.append((name, domain, bonus, tier_key))
    return index


def _priority_bonus(job: JobPosting, index: list[tuple[str, str, float, str]]) -> tuple[float, str | None, str | None]:
    """Returns (bonus, tier_key, matched_name) for the strongest match, or
    (0, None, None) if the job doesn't match any priority target."""
    blob = f"{job.title} {job.company} {job.description}".lower()
    url = (job.url or "").lower()

    best_bonus = 0.0
    best_tier: str | None = None
    best_name: str | None = None
    for name, domain, bonus, tier_key in index:
        matched = (name and name in blob) or (domain and domain in url)
        if matched and (best_tier is None or bonus > best_bonus):
            best_bonus = bonus
            best_tier = tier_key
            best_name = name or domain
    return best_bonus, best_tier, best_name


def validate_and_score(jobs: list[JobPosting], config: dict) -> list[JobPosting]:
    """Returns only the jobs that pass hard filters, each with `.score`,
    `.reasons`, and `.salary_note` populated, sorted best-first."""

    filters = config["filters"]
    salary_cfg = config["salary"]
    search_cfg = config["search"]

    seniority_kw = filters["seniority_keywords"]
    domain_kw = filters["domain_keywords"]
    exclude_kw = filters["exclude_keywords"]
    skill_weights = filters["skill_weights"]
    min_score = filters["min_score_to_alert"]

    locations = search_cfg["locations"]
    primary_location = search_cfg["primary_location"]

    fx_table = salary_cfg["fx_to_aed"]
    target_monthly = salary_cfg["min_monthly"]
    tolerance_ratio = salary_cfg["tolerance_ratio"]

    priority_index = build_priority_index(config.get("priority_targets", {}))

    passed: list[JobPosting] = []

    for job in jobs:
        title = job.title or ""
        blob = f"{job.title} {job.description}"

        if not title:
            continue

        # Location gate: must be Dubai/UAE per config.
        if not _matches_location(job.location or "", locations):
            continue

        # Exclude explicit junior/intern postings outright.
        if _contains_any(blob, exclude_kw):
            continue

        # Must look senior.
        is_senior = _contains_any(title, seniority_kw)
        if not is_senior:
            continue

        # Must be AI/ML/engineering domain.
        is_domain = _contains_any(blob, domain_kw)
        if not is_domain:
            continue

        reasons = ["Senior-level title", "AI/engineering domain match"]

        # Location bonus for Dubai specifically.
        location_bonus = 15 if primary_location.lower() in (job.location or "").lower() else 5
        reasons.append(f"Location: {job.location or 'UAE'}")

        # Skill overlap score (0-100) against resume keywords.
        skill_score, hit_skills = _score_skills(blob, skill_weights)
        if hit_skills:
            reasons.append("Matches resume skills: " + ", ".join(sorted(hit_skills)[:6]))

        # Salary handling: soft filter + bonus, never hard-excludes when undisclosed.
        salary_bonus = 0
        salary_note = "Salary not disclosed"
        max_disclosed = job.salary_max or job.salary_min
        if max_disclosed:
            aed_value = _normalize_salary_to_aed(max_disclosed, job.salary_currency, fx_table)
            if aed_value is not None:
                # Adzuna and most Gulf boards post annual figures; treat values
                # over 3x the monthly target as annual and convert down.
                monthly_aed = aed_value / 12 if aed_value > target_monthly * 3 else aed_value
                if monthly_aed < target_monthly * tolerance_ratio:
                    continue  # disclosed salary clearly below target -> exclude
                salary_bonus = 20 if monthly_aed >= target_monthly else 10
                salary_note = f"~{monthly_aed:,.0f} AED/month disclosed"
                reasons.append(salary_note)

        # Priority-target bonus: ranks known high-paying/target employers
        # (config.yaml priority_targets) above equivalent roles at unknown
        # companies. Can also be negative (e.g. IT services firms that
        # typically undershoot the salary target) to push those down.
        priority_bonus, priority_tier, priority_name = _priority_bonus(job, priority_index)
        if priority_tier:
            reasons.append(f"Priority target ({priority_tier}: {priority_name}, {priority_bonus:+.0f})")

        # Base score reflects that the job already cleared every hard gate
        # (senior title, AI/engineering domain, Dubai/UAE location, no
        # disclosed salary below target). Skill overlap, salary and the
        # priority-target bonus refine the ranking on top of that instead of
        # being able to sink a genuine match just because a short job blurb
        # didn't literally repeat resume keywords.
        score = min(100.0, max(0.0, 35 + skill_score * 0.35 + location_bonus + salary_bonus + priority_bonus))

        if score < min_score:
            continue

        job.score = score
        job.reasons = reasons
        job.salary_note = salary_note
        passed.append(job)

    passed.sort(key=lambda j: j.score, reverse=True)
    return passed

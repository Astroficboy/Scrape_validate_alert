"""Filters and scores scraped jobs against the candidate's target profile:
Dubai/UAE location, senior AI/engineering roles, and (where disclosed) a
45,000 AED/month salary floor — see config/config.yaml for the tunable
keyword lists and weights this module reads.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass

from src.models import JobPosting

logger = logging.getLogger(__name__)


def _contains_any(text: str, needles: list[str]) -> bool:
    text = text.lower()
    return any(needle.lower() in text for needle in needles)


def _contains_word(text: str, needles: list[str]) -> bool:
    """Like _contains_any, but word-bounded — a plain substring match would
    let "intern" fire inside "international", wrongly hard-excluding a
    genuine posting just for mentioning "international team"."""
    text_l = text.lower()
    return any(re.search(rf"(?<!\w){re.escape(n.lower())}(?!\w)", text_l) for n in needles)


def _normalize_salary_to_aed(amount: float, currency: str | None, fx_table: dict) -> float | None:
    currency = (currency or "AED").upper()
    rate = fx_table.get(currency)
    if rate is None:
        return None
    return amount * rate


def _matches_location(location: str, locations: list[str]) -> bool:
    location_l = location.lower()
    return any(loc.lower() in location_l for loc in locations)


# "5+ years", "minimum of 8 years", "8-10 years", "at least 12 yrs"
_YEARS_RE = re.compile(
    r"(\d{1,2})\s*(?:\+|plus)?\s*(?:-|–|to)?\s*(\d{1,2})?\s*\+?\s*(?:years?|yrs?)",
    re.I,
)


def _extract_required_years(text: str) -> int | None:
    """Largest credible 'N years experience' figure in the text, or None if
    the posting doesn't mention a required years-of-experience figure."""
    text_l = text.lower()
    best = None
    for match in _YEARS_RE.finditer(text_l):
        window = text_l[max(0, match.start() - 60): match.end() + 60]
        if "experience" not in window and "exp" not in window:
            continue
        low = int(match.group(1))
        high = int(match.group(2)) if match.group(2) else low
        value = min(low, high)  # the floor is what actually gates you
        if 0 < value <= 30:
            best = value if best is None else max(best, value)
    return best


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


@dataclass
class PriorityTarget:
    name: str
    domain: str
    bonus: float
    tier: str

    @property
    def pattern(self) -> re.Pattern:
        # Word-boundary match so "AWS" doesn't fire inside another word, and
        # names with punctuation ("e&") don't break the regex.
        return re.compile(rf"(?<!\w){re.escape(self.name)}(?!\w)", re.I)


def build_priority_index(priority_targets: dict) -> list[PriorityTarget]:
    """Flattens config.yaml's priority_targets tiers into PriorityTarget
    entries for fast lookup per job."""
    index: list[PriorityTarget] = []
    for tier_key, tier in (priority_targets or {}).items():
        bonus = tier.get("bonus", 0)
        for company in tier.get("companies", []):
            name = (company.get("name") or "").strip()
            domain = (company.get("domain") or "").strip().lower()
            if name or domain:
                index.append(PriorityTarget(name=name, domain=domain, bonus=bonus, tier=tier_key))
    return index


def _priority_bonus(job: JobPosting, index: list[PriorityTarget]) -> tuple[float, str | None, str | None]:
    """Returns (bonus, tier_key, matched_name) for the strongest match, or
    (0, None, None) if the job doesn't match any priority target.

    Deliberately matches only the `company` field and the URL host — never
    the title/description. AWS, Databricks, Oracle and Google Cloud show up
    constantly as *required skills* in AI job postings; matching those
    against the description would wrongly tag half the feed as "big tech".
    A domain hit in the URL always outranks a name match (more specific
    signal), and among name matches the longest company name wins (so "FAB"
    can't outrank "First Abu Dhabi Bank" when both are configured).
    """
    url = (job.url or "").lower()
    company = job.company or ""

    by_domain = [t for t in index if t.domain and t.domain in url]
    by_name = [t for t in index if t.name and company and t.pattern.search(company)]

    pool = by_domain or by_name
    if not pool:
        return 0.0, None, None

    best = max(pool, key=lambda t: (t.bonus, len(t.name)))
    return best.bonus, best.tier, (best.name or best.domain)


def validate_and_score(jobs: list[JobPosting], config: dict) -> list[JobPosting]:
    """Returns only the jobs that pass hard filters, each with `.score`,
    `.reasons`, and `.salary_note` populated, sorted best-first."""

    filters = config["filters"]
    salary_cfg = config["salary"]
    search_cfg = config["search"]
    candidate_cfg = config["candidate"]

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

    ai_years = candidate_cfg.get("ai_years", 0)
    total_years = candidate_cfg.get("total_years", 0)
    years_ceiling = candidate_cfg.get("max_years_tolerated", 12)

    priority_index = build_priority_index(config.get("priority_targets", {}))

    passed: list[JobPosting] = []
    # Funnel telemetry: without this, an empty digest on a day with plenty of
    # raw postings is undiagnosable from the outside — was the location gate
    # too strict, or genuinely nothing senior/AI-relevant came in today?
    rejected: Counter[str] = Counter()

    for job in jobs:
        title = job.title or ""
        blob = f"{job.title} {job.description}"

        if not title:
            rejected["missing title"] += 1
            continue

        # Location gate: must be Dubai/UAE per config.
        if not _matches_location(job.location or "", locations):
            rejected["location not Dubai/UAE"] += 1
            continue

        # Exclude explicit junior/intern postings outright. Word-bounded so
        # "intern" doesn't fire inside "international", etc.
        if _contains_word(blob, exclude_kw):
            rejected["excluded keyword (junior/intern/etc)"] += 1
            continue

        # Must look senior.
        is_senior = _contains_any(title, seniority_kw)
        if not is_senior:
            rejected["no seniority keyword in title"] += 1
            continue

        # Must be AI/ML/engineering domain.
        is_domain = _contains_any(blob, domain_kw)
        if not is_domain:
            rejected["not AI/engineering domain"] += 1
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
                    rejected["disclosed salary below target"] += 1
                    continue
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

        # Years-of-experience required, if the posting states one. A soft
        # signal (never excludes) — required-but-unstated is common and
        # shouldn't be held against a posting.
        years_bonus = 0.0
        required_years = _extract_required_years(blob)
        if required_years is None:
            years_bonus = 2
        elif required_years <= ai_years:
            years_bonus = 8
            reasons.append(f"Asks {required_years}y — matches {ai_years}y hands-on AI experience")
        elif required_years <= total_years:
            years_bonus = 5
            reasons.append(f"Asks {required_years}y — covered by {total_years}y total experience")
        elif required_years <= years_ceiling:
            years_bonus = 0
            reasons.append(f"Asks {required_years}y experience — a stretch")
        else:
            years_bonus = -10
            reasons.append(f"Asks {required_years}y experience — likely out of range")

        # Base score reflects that the job already cleared every hard gate
        # (senior title, AI/engineering domain, Dubai/UAE location, no
        # disclosed salary below target). Skill overlap, salary, years-fit
        # and the priority-target bonus refine the ranking on top of that
        # instead of being able to sink a genuine match just because a short
        # job blurb didn't literally repeat resume keywords.
        score = 35 + skill_score * 0.35 + location_bonus + salary_bonus + priority_bonus + years_bonus

        # Thin-data guard: a title-only posting (e.g. a bare search-result
        # snippet) can't be trusted to outrank a fully-described real match,
        # but a named priority-target employer is itself strong evidence, so
        # the cap lifts by that bonus rather than burying the hit entirely.
        if len(job.description) < 60:
            score = min(score, 72 + max(0.0, priority_bonus))
            reasons.append("Limited detail available — open the link to verify")

        score = min(100.0, max(0.0, score))

        if score < min_score:
            rejected[f"score below min_score_to_alert ({min_score})"] += 1
            continue

        job.score = score
        job.reasons = reasons
        job.salary_note = salary_note
        passed.append(job)

    passed.sort(key=lambda j: j.score, reverse=True)

    if jobs:
        funnel = ", ".join(f"{count} {reason}" for reason, count in rejected.most_common())
        logger.info(
            "Filter funnel: %d raw -> %d passed (%s)",
            len(jobs), len(passed), funnel or "no rejections",
        )

    return passed

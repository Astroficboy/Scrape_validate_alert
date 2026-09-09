"""Formats validated job lists into WhatsApp text and an HTML email digest."""

from __future__ import annotations

from datetime import date

from src.models import JobPosting


def _fmt_salary(job: JobPosting) -> str:
    return job.salary_note or "Salary not disclosed"


def build_whatsapp_text(jobs: list[JobPosting], config: dict) -> str:
    max_jobs = config["digest"]["max_jobs_whatsapp"]
    today = date.today().isoformat()
    lines = [f"*Dubai AI Job Alert — {today}*", f"{len(jobs)} new match(es) found:\n"]

    for i, job in enumerate(jobs[:max_jobs], start=1):
        lines.append(
            f"{i}. *{job.title}*\n"
            f"   {job.company} — {job.location}\n"
            f"   {_fmt_salary(job)} | Match: {job.score:.0f}/100\n"
            f"   {job.url}"
        )

    if len(jobs) > max_jobs:
        lines.append(f"\n+{len(jobs) - max_jobs} more in your email digest.")

    return "\n\n".join(lines)


def build_empty_whatsapp_text() -> str:
    today = date.today().isoformat()
    return f"*Dubai AI Job Alert — {today}*\nNo new matching roles today. Still watching."


def build_email_html(jobs: list[JobPosting], config: dict) -> tuple[str, str]:
    """Returns (subject, html_body)."""
    max_jobs = config["digest"]["max_jobs_email"]
    today = date.today().isoformat()
    subject = f"Dubai AI Job Alert — {len(jobs)} new match(es) — {today}"

    if not jobs:
        html = f"""
        <h2>Dubai AI Job Alert — {today}</h2>
        <p>No new matching roles found today. The system is still running and will
        keep watching Adzuna, Greenhouse, Lever and Bayt for Dubai/UAE senior
        AI &amp; engineering roles at or near AED 45,000/month.</p>
        """
        return subject, html

    rows = []
    for job in jobs[:max_jobs]:
        reasons = "; ".join(job.reasons)
        rows.append(
            f"""
            <tr>
              <td style="padding:10px;border-bottom:1px solid #e5e5e5;">
                <a href="{job.url}" style="font-size:15px;font-weight:600;color:#0b5fff;text-decoration:none;">{job.title}</a><br>
                <span style="color:#555;">{job.company} — {job.location}</span><br>
                <span style="color:#555;">{_fmt_salary(job)} &middot; Match score: {job.score:.0f}/100 &middot; Source: {job.source}</span><br>
                <span style="color:#888;font-size:12px;">{reasons}</span>
              </td>
            </tr>
            """
        )

    html = f"""
    <h2>Dubai AI Job Alert — {today}</h2>
    <p>{len(jobs)} new senior AI/engineering role(s) matching your Dubai job search profile
    (target: AED 45,000/month, available from late Oct/early Nov 2026).</p>
    <table style="border-collapse:collapse;width:100%;max-width:680px;">
      {''.join(rows)}
    </table>
    """
    if len(jobs) > max_jobs:
        html += f"<p>+{len(jobs) - max_jobs} more matches not shown (raised cap: digest.max_jobs_email in config.yaml).</p>"

    return subject, html


def build_failure_alert(failed_sources: list[str]) -> tuple[str, str]:
    today = date.today().isoformat()
    subject = f"[Job Alert System] Source failures — {today}"
    html = (
        f"<p>The daily Dubai job alert run on {today} could not fetch results "
        f"from: <b>{', '.join(failed_sources)}</b>. Other sources still ran "
        f"normally. Check the GitHub Actions log for details.</p>"
    )
    return subject, html

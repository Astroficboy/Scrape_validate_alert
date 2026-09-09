"""Persists which jobs have already been alerted on, so daily runs only
notify about genuinely new postings. Backed by a JSON file that the GitHub
Actions workflow commits back to the repo after each run (see
.github/workflows/daily-job-alert.yml) — that's the system's "database"
since Actions runners are ephemeral.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.models import JobPosting

PRUNE_AFTER_DAYS = 60


class SeenJobsStore:
    def __init__(self, path: Path):
        self.path = path
        self._data: dict[str, dict] = self._load()

    def _load(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    def is_new(self, job: JobPosting) -> bool:
        return job.job_id not in self._data

    def filter_new(self, jobs: list[JobPosting]) -> list[JobPosting]:
        return [j for j in jobs if self.is_new(j)]

    def mark_seen(self, jobs: list[JobPosting]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        for job in jobs:
            self._data[job.job_id] = {
                "title": job.title,
                "company": job.company,
                "url": job.url,
                "first_seen": now,
            }

    def prune(self, days: int = PRUNE_AFTER_DAYS) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        stale = []
        for job_id, record in self._data.items():
            try:
                seen_at = datetime.fromisoformat(record["first_seen"])
            except (KeyError, ValueError):
                continue
            if seen_at < cutoff:
                stale.append(job_id)
        for job_id in stale:
            del self._data[job_id]
        return len(stale)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, sort_keys=True)

    def __len__(self) -> int:
        return len(self._data)

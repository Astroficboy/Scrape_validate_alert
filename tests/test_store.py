import json
from datetime import datetime, timedelta, timezone

from src.models import JobPosting
from src.store import SeenJobsStore


def _job(url="https://example.com/job/1") -> JobPosting:
    return JobPosting(source="test", title="Lead AI Engineer", company="Acme", location="Dubai", url=url)


def test_new_store_treats_all_jobs_as_new(tmp_path):
    store = SeenJobsStore(tmp_path / "seen.json")
    jobs = [_job()]
    assert store.filter_new(jobs) == jobs


def test_marked_jobs_are_no_longer_new(tmp_path):
    store = SeenJobsStore(tmp_path / "seen.json")
    job = _job()
    store.mark_seen([job])
    assert store.filter_new([job]) == []


def test_persists_across_instances(tmp_path):
    path = tmp_path / "seen.json"
    job = _job()

    store1 = SeenJobsStore(path)
    store1.mark_seen([job])
    store1.save()

    store2 = SeenJobsStore(path)
    assert store2.filter_new([job]) == []


def test_prune_removes_stale_entries(tmp_path):
    path = tmp_path / "seen.json"
    old_date = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    path.write_text(json.dumps({"abc123": {"title": "x", "company": "y", "url": "z", "first_seen": old_date}}))

    store = SeenJobsStore(path)
    removed = store.prune(days=60)
    assert removed == 1
    assert len(store) == 0


def test_different_jobs_get_different_ids():
    a = _job(url="https://example.com/job/1")
    b = _job(url="https://example.com/job/2")
    assert a.job_id != b.job_id

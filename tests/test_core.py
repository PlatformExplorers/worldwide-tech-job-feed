from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path

import pytest
import requests
import yaml

from src.config import AppConfig, load_config
from src.discord_client import DiscordClient, build_embed
from src.filters import is_relevant
from src.models import Job, normalize_text
from src.scheduler import collect_sources, run
from src.sources.arbeitnow import ArbeitnowSource
from src.sources.himalayas import HimalayasSource
from src.sources.jobicy import JobicySource
from src.sources.remotive import RemotiveSource
from src.state import JobState
from src.utils.url_utils import canonicalize_url, valid_http_url


def app_config() -> AppConfig:
    return AppConfig(
        raw={
            "discord": {"show_timestamp": False, "retries": 1},
            "filters": {
                "include_keywords": ["software engineer"],
                "job_titles": [],
                "exclude_keywords": ["unpaid"],
                "countries": [],
                "remote_only": False,
            },
        },
        state_path="unused.json",
        discord_webhook_url="https://discord.com/api/webhooks/123/token",
        max_posts_per_run=40,
        max_job_age_days=30,
        first_run_backfill=False,
        request_timeout=1,
        request_retries=0,
        logging_level="INFO",
    )


def make_job(**overrides) -> Job:
    values = {
        "source": "test",
        "source_job_id": "id-1",
        "title": "Senior Software Engineer",
        "company": "Example Inc",
        "url": "https://jobs.example.com/role?id=7&utm_source=feed",
        "location": "Berlin, Germany",
        "description": (
            "Build software products with a collaborative engineering team and modern systems."
        ),
    }
    values.update(overrides)
    return Job(**values)


def test_normalization_and_url_canonicalization() -> None:
    assert normalize_text("  Déveloper—Cloud  ") == "developer cloud"
    assert canonicalize_url("HTTPS://Jobs.example.com/role/?utm_source=feed&id=7#apply") == (
        "https://jobs.example.com/role?id=7"
    )


def test_filter_uses_whole_terms_and_configured_technology() -> None:
    config = app_config()
    assert is_relevant(make_job(), config)
    assert not is_relevant(make_job(title="Marketing Writer", description="it is useful"), config)
    assert not is_relevant(make_job(description="Unpaid software engineer opportunity"), config)


@pytest.mark.parametrize(
    ("title", "description", "expected"),
    [
        ("Graduate Data Analyst", "", True),
        ("Junior Cyber Security Consultant", "", True),
        ("Summer Software Internship", "", True),
        ("IT Intern", "", True),
        ("Fall Computer Science Internship", "", True),
        ("Junior Cloud Support Associate", "", True),
        ("Senior Software Engineer", "", True),
        ("Graduate Marketing Intern", "Support brand campaigns.", False),
        ("Junior Sales Associate", "Sell consumer products.", False),
        ("Software Internship", "This is an unpaid internship.", False),
    ],
)
def test_configured_technology_filter_includes_entry_level_roles(
    title: str, description: str, expected: bool
) -> None:
    config = load_config(Path(__file__).resolve().parents[1] / "config.yaml")
    assert is_relevant(make_job(title=title, description=description), config) is expected


def test_state_persists_only_hashes_and_prevents_repeats(tmp_path) -> None:
    path = tmp_path / "seen.json"
    state = JobState(str(path))
    job = make_job()
    state.mark_seen(job)
    state.initialized_sources.add(job.source)
    state.save()

    raw = path.read_text(encoding="utf-8")
    assert job.title not in raw
    assert job.url not in raw
    assert job.description not in raw
    assert all(len(value) == 64 for value in json.loads(raw)["fingerprints"])
    restored = JobState(str(path))
    assert restored.has_seen(job)
    assert restored.initialized_sources == {"test"}


def test_source_baseline_and_seen_fingerprints_skip_repeat(monkeypatch) -> None:
    config = app_config()
    old_job = make_job()
    jobs = [old_job]

    class FakeSource:
        def fetch(self):
            return list(jobs)

    monkeypatch.setattr("src.scheduler.source_instance", lambda *_args: FakeSource())
    state = JobState("unused.json")

    outcomes, candidates = collect_sources(config, state, source_filter="jobicy")
    assert outcomes["jobicy"] == 0
    assert candidates == []
    assert "jobicy" in state.initialized_sources

    jobs.append(
        make_job(
            source_job_id="new-id",
            title="Senior Software Engineer II",
            url="https://jobs.example.com/role?id=8",
        )
    )
    _, candidates = collect_sources(config, state, source_filter="jobicy")
    assert [job.title for job in candidates] == ["Senior Software Engineer II"]


def test_arbeitnow_parser_maps_known_fields() -> None:
    source = object.__new__(ArbeitnowSource)
    job = source._normalize(
        {
            "slug": "python-engineer",
            "title": "Python Engineer",
            "company_name": "Acme",
            "url": "https://example.com/jobs/123",
            "location": "Worldwide",
            "remote": True,
            "job_types": ["Full-time"],
            "tags": ["Python", "Cloud"],
            "description": "<p>Build APIs</p>",
            "created_at": "2026-01-01T00:00:00Z",
        }
    )
    assert job is not None
    assert job.source_job_id == "python-engineer"
    assert job.source_website == "https://www.arbeitnow.com"
    assert job.work_arrangement == "remote"
    assert job.skills == ["Python", "Cloud"]
    assert job.description == "Build APIs"


def test_arbeitnow_pagination_has_a_hard_upper_bound() -> None:
    source = object.__new__(ArbeitnowSource)
    source.options = {"max_pages": 100000}
    requests = []

    class Response:
        @staticmethod
        def json():
            return {"data": [], "links": {"next": "present"}}

    source.get = lambda _url, params: requests.append(params["page"]) or Response()
    assert source.fetch() == []
    assert requests == list(range(1, 11))


def test_jobicy_url_is_used_as_the_original_listing_link() -> None:
    source = object.__new__(JobicySource)
    job = source._normalize(
        {
            "id": 123,
            "jobTitle": "Software Engineer",
            "companyName": "Acme",
            "url": "https://jobicy.com/jobs/123",
            "jobGeo": "Canada",
        }
    )
    assert job is not None
    assert job.url == "https://jobicy.com/jobs/123"
    assert job.source_website == job.url


def test_discord_embed_disables_mentions_and_clips_content() -> None:
    job = make_job(title="Software Engineer " + "x" * 300, description="d" * 5000)
    embed = build_embed(job, app_config())
    assert len(embed["title"]) <= 256
    assert len(embed["description"]) <= 4096
    assert embed["url"] == job.url

    class Response:
        status_code = 200
        headers = {}

        @staticmethod
        def raise_for_status() -> None:
            return None

        @staticmethod
        def json() -> dict[str, str]:
            return {"id": "message-123"}

    class Session:
        payload = None

        def post(self, url, **kwargs):
            self.payload = kwargs["json"]
            return Response()

    session = Session()
    client = DiscordClient(app_config(), session=session)
    assert client.send_job(make_job(title="@everyone engineer")) == "message-123"
    assert session.payload["allowed_mentions"] == {"parse": []}
    assert client.send_test() == "message-123"
    assert session.payload["content"].startswith("TEST PREVIEW")
    assert "TEST PREVIEW" in session.payload["embeds"][0]["title"]


def test_discord_missing_secret_fails_closed() -> None:
    config = app_config()
    config.discord_webhook_url = None
    with pytest.raises(ValueError, match="DISCORD_WEBHOOK_URL"):
        DiscordClient(config)


@pytest.mark.parametrize(
    "url",
    [
        "http://jobs.example.com/role",
        "javascript:alert(1)",
        "https://user:pass@jobs.example.com/role",
        "https://localhost/apply",
        "https://127.0.0.1/apply",
        "https://jobs.example.com/role?token=secret",
    ],
)
def test_unsafe_application_urls_are_rejected(url: str) -> None:
    assert not valid_http_url(url)
    with pytest.raises(ValueError, match="safe HTTPS URL"):
        build_embed(make_job(url=url), app_config())


def test_valid_application_url_is_preserved_in_discord_embed() -> None:
    url = "https://careers.example.com/apply?gh_jid=123"
    embed = build_embed(make_job(url=url), app_config())
    assert embed["url"] == url
    assert any(
        field["name"] == "Apply / original listing"
        and field["value"] == f"[Open source link]({url})"
        for field in embed["fields"]
    )


def test_invalid_config_is_rejected(tmp_path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "runtime:\n  max_posts_per_run: 0\nsources: {}\ndiscord: {}\nfilters: {}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="max_posts_per_run"):
        load_config(path)


def test_configured_post_limit_is_preserved_and_enforced(tmp_path, monkeypatch) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "runtime:\n  max_posts_per_run: 3\nsources:\n  jobicy:\n    enabled: true\n",
        encoding="utf-8",
    )
    config = load_config(path)
    config.discord_webhook_url = "https://discord.com/api/webhooks/123/token"
    jobs = [
        make_job(
            title=f"Software Engineer {index}",
            source_job_id=str(index),
            url=f"https://jobs.example.com/role/{index}",
        )
        for index in range(5)
    ]
    sent = []

    class Source:
        def fetch(self):
            return jobs

    class Client:
        def __init__(self, _config):
            pass

        def send_job(self, job):
            sent.append(job)

    monkeypatch.setattr("src.scheduler.source_instance", lambda *_args: Source())
    monkeypatch.setattr("src.scheduler.DiscordClient", Client)
    state = JobState(str(tmp_path / "state.json"))
    state.initialized_sources.add("jobicy")
    outcomes = run(config, state)
    assert config.max_posts_per_run == 3
    assert outcomes["published"] == 3
    assert outcomes["eligible_again_next_run"] == 2
    assert sent == jobs[:3]
    assert all(state.has_seen(job) for job in jobs[:3])
    assert not any(state.has_seen(job) for job in jobs[3:])


def test_himalayas_preserves_application_link_and_maps_fields() -> None:
    source = HimalayasSource(app_config(), {})
    url = "https://himalayas.app/companies/acme/jobs/developer?utm_source=api"
    job = source._normalize(
        {
            "title": "Software Engineer",
            "companyName": "Acme",
            "guid": "listing-123",
            "applicationLink": url,
            "locationRestrictions": ["Canada", "United States"],
            "pubDate": 1767225600,
            "expiryDate": 4102444800,
            "minSalary": 100000,
            "maxSalary": 150000,
            "salaryPeriod": "annual",
            "currency": "USD",
            "description": "<p>Build reliable software.</p>",
        }
    )
    assert job is not None
    assert job.url == url
    assert job.source_website == url
    assert job.location == "Canada, United States"
    assert job.salary_min == 100000
    assert job.salary_period == "annual"
    assert job.published_at == "2026-01-01T00:00:00+00:00"
    assert job.description == "Build reliable software."
    embed = build_embed(job, app_config())
    assert embed["url"] == url
    assert any(field["value"] == f"[Himalayas]({url})" for field in embed["fields"])
    assert (
        source._normalize(
            {"title": "Engineer", "companyName": "Acme", "applicationLink": url, "expiryDate": 1}
        )
        is None
    )


def test_himalayas_pagination_is_bounded_and_keeps_fixed_endpoint() -> None:
    source = HimalayasSource(app_config(), {"max_pages": 100000})
    calls = []

    class Response:
        def json(self):
            return {"jobs": [{}], "nextCursor": f"cursor-{len(calls)}"}

    source.get = lambda url, params: calls.append((url, params.copy())) or Response()
    assert source.fetch() == []
    assert len(calls) == 10
    assert all(url == source.endpoint and params["limit"] == 20 for url, params in calls)
    assert calls[1][1]["cursor"] == "cursor-1"


def test_himalayas_repeated_cursor_reports_failure() -> None:
    source = HimalayasSource(app_config(), {})

    class Response:
        def json(self):
            return {"jobs": [{}], "nextCursor": "repeated"}

    source.get = lambda *_args, **_kwargs: Response()
    with pytest.raises(ValueError, match="repeated pagination cursor"):
        source.fetch()


def test_remotive_caps_results_and_retains_attribution() -> None:
    source = RemotiveSource(app_config(), {"limit": 1})
    url = "https://remotive.com/remote-jobs/software-development/developer-123"

    class Response:
        def json(self):
            return {
                "jobs": [{"id": 123, "title": "Engineer", "company_name": "Acme", "url": url}] * 3
            }

    source.get = lambda *_args, **_kwargs: Response()
    jobs = source.fetch()
    assert len(jobs) == 1
    assert jobs[0].source_website == url


def test_remotive_request_retry_override_prevents_extra_requests(monkeypatch) -> None:
    config = app_config()
    config.request_retries = 3
    source = RemotiveSource(config, {"request_retries": 0})
    attempts = []

    def fail(*_args, **_kwargs):
        attempts.append(1)
        raise requests.Timeout("Simulated timeout")

    monkeypatch.setattr(source.session, "get", fail)
    with pytest.raises(requests.Timeout):
        source.fetch()
    assert len(attempts) == 1


def test_failed_poll_is_persisted_and_respects_interval(monkeypatch, tmp_path) -> None:
    config = app_config()
    config.raw["sources"] = {"remotive": {"enabled": True, "poll_interval_minutes": 360}}
    calls = []

    class Source:
        def fetch(self):
            calls.append(1)
            raise requests.Timeout("Simulated timeout")

    monkeypatch.setattr("src.scheduler.source_instance", lambda *_args: Source())
    state = JobState(str(tmp_path / "seen.json"))
    outcomes, candidates = collect_sources(config, state)
    assert outcomes["remotive"] == "error: Timeout"
    assert candidates == []
    state.save()
    restored = JobState(str(state.path))
    assert "remotive" not in restored.last_success
    outcomes, _ = collect_sources(config, restored)
    assert outcomes["remotive"] == "skipped: polling interval"
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("source", "settings", "message"),
    [
        ("himalayas", "poll_interval_minutes: 60", "at least 120"),
        ("himalayas", "poll_interval_minutes: 120\n    max_pages: 11", "max_pages"),
        ("remotive", "poll_interval_minutes: 60\n    request_retries: 0", "at least 360"),
        ("remotive", "poll_interval_minutes: 360\n    request_retries: 1", "request_retries"),
    ],
)
def test_source_limits_are_validated(tmp_path, source, settings, message) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(f"sources:\n  {source}:\n    enabled: true\n    {settings}\n", encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        load_config(path)


def test_workflow_creates_and_updates_hash_only_state_branch(tmp_path) -> None:
    workflow_path = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "jobs.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    step = next(
        item
        for item in workflow["jobs"]["aggregate"]["steps"]
        if item.get("name") == "Save hashed deduplication state"
    )
    commands = [
        shlex.split(line.strip())
        for line in step["run"].splitlines()
        if line.strip().startswith("git worktree add ")
    ]
    application = tmp_path / "application"
    application.mkdir()
    remote = tmp_path / "remote.git"
    worktree = tmp_path / "job-state"

    def git(*args, cwd=application):
        return subprocess.run(
            ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
        ).stdout.strip()

    git("init", "-b", "main")
    git("config", "user.name", "Workflow test")
    git("config", "user.email", "test@example.com")
    (application / "README.md").write_text("Application source\n", encoding="utf-8")
    git("add", "README.md")
    git("commit", "-m", "Initial application")
    application_commit = git("rev-parse", "HEAD")
    git("init", "--bare", str(remote))
    git("remote", "add", "origin", str(remote))

    def add_worktree(command):
        args = [str(worktree) if arg == "$RUNNER_TEMP/job-state" else arg for arg in command[1:]]
        git(*args)

    add_worktree(commands[1])
    assert not (worktree / "README.md").exists()
    state_path = worktree / "data" / "seen-hashes.json"
    state = JobState(str(state_path))
    first = make_job()
    state.mark_seen(first)
    state.save()
    git("add", "data/seen-hashes.json", cwd=worktree)
    git("commit", "-m", "Initial fingerprints", cwd=worktree)
    git("push", "origin", "HEAD:refs/heads/job-state", cwd=worktree)
    git("worktree", "remove", str(worktree))
    git("fetch", "origin", "refs/heads/job-state:refs/remotes/origin/job-state")

    add_worktree(commands[0])
    restored = JobState(str(state_path))
    assert restored.has_seen(first)
    second = make_job(source_job_id="second", url="https://jobs.example.com/second")
    restored.mark_seen(second)
    restored.save()
    git("add", "data/seen-hashes.json", cwd=worktree)
    git("commit", "-m", "Update fingerprints", cwd=worktree)
    git("push", "origin", "HEAD:refs/heads/job-state", cwd=worktree)
    git("worktree", "remove", str(worktree))
    git("fetch", "origin", "refs/heads/job-state:refs/remotes/origin/job-state")
    assert git("ls-tree", "-r", "--name-only", "origin/job-state") == "data/seen-hashes.json"
    raw = git("show", "origin/job-state:data/seen-hashes.json")
    assert first.url not in raw and second.url not in raw
    assert state.seen < set(json.loads(raw)["fingerprints"])
    assert git("rev-parse", "HEAD") == application_commit

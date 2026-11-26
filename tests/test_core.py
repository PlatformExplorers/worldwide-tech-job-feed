from __future__ import annotations

import json

import pytest

from src.config import AppConfig, load_config
from src.discord_client import DiscordClient, build_embed
from src.filters import is_relevant
from src.models import Job, normalize_text
from src.scheduler import collect_sources
from src.sources.arbeitnow import ArbeitnowSource
from src.sources.jobicy import JobicySource
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

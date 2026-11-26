"""Adapter for explicitly configured company or job-board RSS/Atom feeds."""

from __future__ import annotations

import feedparser

from src.models import Job
from src.sources.base import JobSource, clean_html, text_or_none
from src.utils.url_utils import valid_http_url


class RSSSource(JobSource):
    name = "rss"

    def fetch(self) -> list[Job]:
        feeds = self.options.get("feeds", [])
        if not isinstance(feeds, list):
            raise ValueError("RSS feeds must be a list")
        jobs = []
        for feed in feeds:
            if not isinstance(feed, dict) or not feed.get("url"):
                raise ValueError("Each RSS feed must contain a URL")
            feed_url = str(feed["url"])
            if not valid_http_url(feed_url):
                raise ValueError("Configured RSS feed URLs must be safe HTTPS URLs")
            response = self.get(feed_url, allow_redirects=False)
            parsed = feedparser.parse(response.content)
            if parsed.bozo and not parsed.entries:
                raise ValueError(f"Unable to parse configured feed: {feed.get('name', 'unnamed')}")
            for entry in parsed.entries:
                title, url = text_or_none(entry.get("title")), text_or_none(entry.get("link"))
                if not title or not url:
                    continue
                published = entry.get("published") or entry.get("updated")
                jobs.append(
                    Job(
                        source=self.name,
                        source_job_id=text_or_none(entry.get("id")),
                        title=title,
                        company=str(feed.get("company", feed.get("name", "Unknown employer"))),
                        url=url,
                        location=text_or_none(entry.get("location")),
                        description=clean_html(entry.get("summary") or entry.get("description")),
                        published_at=text_or_none(published),
                    )
                )
        return jobs

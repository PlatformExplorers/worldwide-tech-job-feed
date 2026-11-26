# Worldwide Tech Job Feed

Worldwide Tech Job Feed collects technology job listings from configured public
sources and posts new opportunities to Platform Explorers Discord channel. It runs on GitHub
Actions and uses fingerprints to avoid repeatedly posting the same listing.

Enabled sources are Jobicy, Himalayas, and Remotive. Listings retain source credit
and original listing links; LinkedIn and other authenticated sites are not scraped.

Technology opportunities include graduate, junior, and internship roles in all
seasons alongside experienced roles. Listings mentioning unpaid work are excluded.
Posting is capped at three opportunities per workflow run across all sources combined.

The Discord webhook is configured through the `DISCORD_WEBHOOK_URL` GitHub
Actions secret. See [SECURITY.md](SECURITY.md) for security guidance.

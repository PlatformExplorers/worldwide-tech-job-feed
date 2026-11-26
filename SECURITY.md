# Security policy

## Secrets and private data

- Treat the Discord webhook URL as a password: anyone with it can post to the channel.
- For GitHub Actions, store it in the `DISCORD_WEBHOOK_URL` repository secret. For local use, provide it through the process environment; `.env` is ignored by Git and is not loaded automatically.
- Never commit `.env`, webhook URLs, API keys, OAuth tokens, or mailbox data. Keep `.env.example` free of credentials.
- If a webhook is exposed, delete or rotate it in Discord and update the GitHub Actions secret and any local copy.
- Current adapters do not access email or store personal mailbox content.
- The `job-state` branch contains SHA-256 fingerprints and source markers only. It does not contain job descriptions, titles, or raw application URLs.
- Use only source data and redistribution patterns permitted by the relevant publishers.

## External data

Listings are untrusted. HTML is reduced to plain text, HTTPS application links are validated, and Discord mentions are disabled. The application does not fetch application URLs. Source adapters use request timeouts, bounded retries, finite page/request limits, and independent error handling. Link validation reduces risk but cannot guarantee that an external job page is benign.

## Source access and attribution

- Jobicy remains enabled. [Himalayas](https://himalayas.app/docs/remote-jobs-api) and [Remotive](https://github.com/remotive-com/remote-jobs-api) supply public remote-job APIs without credentials. Preserve source credit and the API-provided listing link; do not syndicate their listings to other job boards, aggregators, Google Jobs, or LinkedIn Jobs.
- Himalayas is polled every two hours, with at most five pages of 20 listings per poll. Its `applicationLink` is used unchanged; expired listings are skipped.
- Remotive is polled every six hours without automatic request retries. Failed polling attempts also count toward the interval.
- Greenhouse, Lever, and RSS remain opt-in until specific employer boards or feeds and their permitted use are verified. Arbeitnow remains disabled because redistribution permission is unverified.
- Newly enabled sources establish fingerprint baselines on their first successful poll, rather than flooding the channel with existing listings. Coverage is bounded, not an exhaustive mirror of every job.

## Reporting

Report security issues privately to the repository maintainer rather than filing a public issue with exploit details.

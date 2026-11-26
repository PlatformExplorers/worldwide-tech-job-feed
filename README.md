# Worldwide Tech Job Feed

Worldwide Tech Job Feed collects technology job listings from configured public
sources and posts new opportunities to Platform Explorers Discord channel. It runs on GitHub
Actions and uses fingerprints to avoid repeatedly posting the same listing.

The Discord webhook is configured through the `DISCORD_WEBHOOK_URL` GitHub
Actions secret. See [SECURITY.md](SECURITY.md) for security guidance.

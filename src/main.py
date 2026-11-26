"""Command-line entry point for the job feed."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from src.config import load_config
from src.discord_client import DiscordClient
from src.scheduler import SOURCE_MODULES, collect_sources, run
from src.state import JobState
from src.utils.logger import configure_logging

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Aggregate technology jobs and publish them to Discord."
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--dry-run", action="store_true", help="Fetch and filter without persisting or publishing"
    )
    modes.add_argument(
        "--test-discord", action="store_true", help="Send a labelled test message to the webhook"
    )
    modes.add_argument(
        "--initialize", action="store_true", help="Create an empty deduplication state file"
    )
    modes.add_argument("--stats", action="store_true", help="Show deduplication state counts")
    modes.add_argument(
        "--check-sources",
        action="store_true",
        help="Fetch enabled sources and report listing counts",
    )
    modes.add_argument("--source", choices=sorted(SOURCE_MODULES), help="Run one configured source")
    modes.add_argument(
        "--run", action="store_true", help="Fetch enabled sources and publish queued jobs"
    )
    parser.add_argument("--config", default="config.yaml", help="Configuration file path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        configure_logging(config.logging_level)
        if args.test_discord:
            message_id = DiscordClient(config).send_test()
            print(json.dumps({"test_message_sent": True, "message_id": message_id}))
            return 0

        state = JobState(config.state_path)
        if args.initialize:
            state.save()
            print(f"Deduplication state initialized: {config.state_path}")
        elif args.stats:
            print(
                json.dumps(
                    {
                        "fingerprints": len(state.seen),
                        "initialized_sources": len(state.initialized_sources),
                    },
                    sort_keys=True,
                )
            )
        elif args.check_sources:
            outcomes, _ = collect_sources(config, state, check_only=True)
            print(json.dumps(outcomes, sort_keys=True))
            return int(any(str(value).startswith("error:") for value in outcomes.values()))
        elif args.dry_run:
            outcomes, candidates = collect_sources(config, state)
            print(
                json.dumps(
                    {"sources": outcomes, "publishable_preview": len(candidates)},
                    sort_keys=True,
                )
            )
        else:
            outcomes = run(config, state, source_filter=args.source)
            state.save()
            print(json.dumps(outcomes, sort_keys=True))
            return int(
                any(str(value).startswith("error:") for value in outcomes.values())
                or "error" in outcomes
                or "discord_error" in outcomes
            )
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        LOGGER.error("%s: %s", type(exc).__name__, exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())

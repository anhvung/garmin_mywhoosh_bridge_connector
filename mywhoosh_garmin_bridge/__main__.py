"""CLI entry point: python -m mywhoosh_garmin_bridge"""

import argparse
import logging
import sys

from dotenv import load_dotenv

from .config import Config
from .sync import sync


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mywhoosh-garmin-bridge",
        description="Sync indoor trainer rides from intervals.icu to Garmin Connect",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Process and rewrite rides but skip the Garmin upload",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=None,
        help="How many days back to scan (default: BRIDGE_LOOKBACK_DAYS or 7)",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug logging")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    load_dotenv()
    try:
        config = Config.from_env()
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        print("Copy .env.example to .env and fill in your credentials.", file=sys.stderr)
        return 2

    if args.dry_run:
        config = Config(
            icu_api_key=config.icu_api_key,
            icu_athlete_id=config.icu_athlete_id,
            garmin_email=config.garmin_email,
            garmin_password=config.garmin_password,
            data_dir=config.data_dir,
            lookback_days=args.lookback_days or config.lookback_days,
            dry_run=True,
        )
    elif args.lookback_days is not None:
        config = Config(
            icu_api_key=config.icu_api_key,
            icu_athlete_id=config.icu_athlete_id,
            garmin_email=config.garmin_email,
            garmin_password=config.garmin_password,
            data_dir=config.data_dir,
            lookback_days=args.lookback_days,
            dry_run=config.dry_run,
        )

    result = sync(config)
    return 0 if result.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

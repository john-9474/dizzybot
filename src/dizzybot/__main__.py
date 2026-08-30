from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from importlib.metadata import version

from pydantic import ValidationError

from dizzybot.composition import build_services
from dizzybot.config import format_validation_error, load_config


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DizzyBot Discord music bot")
    parser.add_argument("--config", default=None, help="Path to the YAML configuration file")
    parser.add_argument(
        "--check-config", action="store_true", help="Validate configuration without connecting"
    )
    parser.add_argument("--version", action="version", version=version("dizzybot"))
    return parser


def main() -> None:
    arguments = _parser().parse_args()
    try:
        config = load_config(arguments.config)
    except (OSError, ValueError, ValidationError) as error:
        message = (
            format_validation_error(error) if isinstance(error, ValidationError) else str(error)
        )
        print(f"Invalid configuration:\n{message}", file=sys.stderr)
        raise SystemExit(2) from error

    logging.basicConfig(
        level=getattr(logging, config.logging.level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if arguments.check_config:
        print("Configuration is valid.")
        return
    services = build_services(config)
    asyncio.run(services.runtime.start())


if __name__ == "__main__":
    main()

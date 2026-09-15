"""Run one conservative Lyra recovery check or monitor after logon."""

from __future__ import annotations

import argparse
from pathlib import Path
import time

from lyra.watchdog import WorkstationWatchdog


ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--monitor", action="store_true")
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument("--failure-threshold", type=int, default=3)
    parser.add_argument("--cooldown", type=int, default=300)
    parser.add_argument(
        "--iterations", type=int, default=None,
        help="Stop after this many monitor checks (validation only)",
    )
    args = parser.parse_args(argv)
    if args.iterations is not None and args.iterations < 1:
        parser.error("--iterations must be at least 1")
    watchdog = WorkstationWatchdog(
        ROOT, failure_threshold=args.failure_threshold, cooldown_seconds=args.cooldown
    )
    completed = 0
    while True:
        outcome = watchdog.tick()
        print(
            f"{outcome.disposition}: failures={outcome.consecutive_failures} "
            f"action={outcome.action or 'none'}"
        )
        completed += 1
        if not args.monitor or (args.iterations is not None and completed >= args.iterations):
            return 1 if outcome.disposition == "failed" else 0
        time.sleep(max(10, min(args.interval, 300)))


if __name__ == "__main__":
    raise SystemExit(main())

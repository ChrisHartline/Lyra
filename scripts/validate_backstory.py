from __future__ import annotations

import argparse
from pathlib import Path

from lyra.backstory import DEFAULT_MAP, load_backstory_map, validate_backstory_map


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the W9.2 backstory map")
    parser.add_argument("--map", type=Path, default=DEFAULT_MAP)
    args = parser.parse_args()

    errors = validate_backstory_map(args.map)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    backstory = load_backstory_map(args.map)
    print(
        "VALID: backstory map "
        f"({len(backstory.payload['sources'])} sources; "
        f"{len(backstory.payload['topics'])} topics; "
        f"{len(backstory.pending_reviews)} pending reviews)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

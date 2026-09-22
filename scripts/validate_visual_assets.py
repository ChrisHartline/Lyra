"""Validate the W9.1 visual-reference catalog and local asset files."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from lyra.visual_assets import DEFAULT_CATALOG, load_catalog, validate_catalog


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("catalog", nargs="?", type=Path, default=DEFAULT_CATALOG)
    args = parser.parse_args()
    errors = validate_catalog(args.catalog)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    catalog = load_catalog(args.catalog)
    counts = Counter(asset["canon_status"] for asset in catalog["assets"])
    pending = [
        review["review_id"]
        for review in catalog["review_items"]
        if review["status"] == "pending_human"
    ]
    print(
        "VALID: visual asset catalog "
        f"({len(catalog['assets'])} assets; "
        f"approved={counts['approved']}, reference={counts['reference']}, "
        f"candidate={counts['candidate']}; exact_duplicates=0)"
    )
    if pending:
        print("PENDING HUMAN REVIEW: " + ", ".join(pending))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Starter figure renderer.

This script is intentionally conservative. It expects source data for plots
and will not fabricate values.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("spec", type=Path, help="Path to figure spec JSON")
    args = parser.parse_args()

    spec = json.loads(args.spec.read_text())
    source = spec.get("source", {})

    if source.get("type") in {"data", "experiment"} and not source.get("path"):
        raise SystemExit("Data or experiment figures require a source.path")

    print(f"Figure spec loaded: {spec.get('figure_id')}")
    print("Implement TikZ, Graphviz, or Matplotlib rendering here.")


if __name__ == "__main__":
    main()

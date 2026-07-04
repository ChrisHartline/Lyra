#!/usr/bin/env python3
"""Check for common citation TODOs and missing BibTeX hints in a LaTeX file."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("tex", type=Path)
    args = parser.parse_args()

    text = args.tex.read_text(errors="ignore")
    todos = [line for line in text.splitlines() if "TODO" in line.upper()]
    cites = sorted(set(re.findall(r"\\cite\{([^}]+)\}", text)))

    print(f"Citations found: {len(cites)}")
    for cite in cites:
        print(f" - {cite}")

    print(f"TODO lines found: {len(todos)}")
    for todo in todos[:50]:
        print(f" - {todo.strip()}")


if __name__ == "__main__":
    main()

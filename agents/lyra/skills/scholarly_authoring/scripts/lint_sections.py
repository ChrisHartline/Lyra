#!/usr/bin/env python3
"""List LaTeX section structure from main.tex."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("tex", type=Path)
    args = parser.parse_args()

    text = args.tex.read_text(errors="ignore")
    sections = re.findall(r"\\section\{([^}]+)\}", text)
    print("Sections:")
    for idx, section in enumerate(sections, start=1):
        print(f"{idx}. {section}")


if __name__ == "__main__":
    main()

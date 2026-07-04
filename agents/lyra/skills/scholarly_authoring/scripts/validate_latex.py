#!/usr/bin/env python3
"""Lightweight LaTeX project validator for generated papers."""

from __future__ import annotations

import argparse
from pathlib import Path

REQUIRED_IEEE_MARKERS = [
    "\\documentclass",
    "\\begin{document}",
    "\\maketitle",
    "\\begin{abstract}",
    "\\bibliography",
    "\\end{document}",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path, help="Publication project directory")
    args = parser.parse_args()

    main_tex = args.project / "main.tex"
    if not main_tex.exists():
        raise SystemExit("Missing main.tex")

    text = main_tex.read_text(errors="ignore")
    missing = [m for m in REQUIRED_IEEE_MARKERS if m not in text]
    todos = [line.strip() for line in text.splitlines() if "TODO" in line.upper()]

    print("LaTeX validation report")
    print("=======================")
    print(f"main.tex: {main_tex}")
    print(f"Missing required markers: {len(missing)}")
    for item in missing:
        print(f" - {item}")
    print(f"TODO lines: {len(todos)}")
    for line in todos[:75]:
        print(f" - {line}")

    if missing:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

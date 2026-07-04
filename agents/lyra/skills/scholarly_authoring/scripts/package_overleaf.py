#!/usr/bin/env python3
"""Package a LaTeX publication directory into an Overleaf-ready zip."""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

EXCLUDE_DIRS = {".git", "__pycache__"}
EXCLUDE_SUFFIXES = {".aux", ".log", ".out", ".toc", ".synctex.gz"}


def should_include(path: Path) -> bool:
    if any(part in EXCLUDE_DIRS for part in path.parts):
        return False
    if any(str(path).endswith(suffix) for suffix in EXCLUDE_SUFFIXES):
        return False
    return path.is_file()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    project = args.project.resolve()
    output = args.output or project.with_suffix(".zip")

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in project.rglob("*"):
            if should_include(path):
                zf.write(path, path.relative_to(project))

    print(f"Created {output}")


if __name__ == "__main__":
    main()

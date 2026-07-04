#!/usr/bin/env python3
"""Starter bibliography copier.

Copies a verified library.bib into a publication project as references.bib.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("library", type=Path)
    parser.add_argument("project", type=Path)
    args = parser.parse_args()

    if not args.library.exists():
        raise SystemExit(f"Missing library: {args.library}")
    args.project.mkdir(parents=True, exist_ok=True)
    target = args.project / "references.bib"
    shutil.copyfile(args.library, target)
    print(f"Copied {args.library} -> {target}")


if __name__ == "__main__":
    main()

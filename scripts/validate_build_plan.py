"""Validate that the Lyra build plan has one definition and status per gate."""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = ROOT / "docs" / "lyra_build_plan.md"

DEFINITION_PATTERNS = (
    re.compile(r"^\*\*([A-Z]\d+(?:\.\d+)?)\s+—"),
    re.compile(r"^###\s+([A-Z]\d+(?:\.\d+)?)\s+—"),
)
PROGRESS_PATTERN = re.compile(r"^\|\s*([A-Z]\d+(?:\.\d+)?)\s*\|")
HIDDEN_RANGE_PATTERN = re.compile(
    r"(?<![A-Z-])([A-Z]\d+(?:\.\d+)?)\s*[–-]\s*([A-Z]\d+(?:\.\d+)?)\b"
)


def _natural_key(gate_id: str) -> tuple[int, int, int]:
    if gate_id.startswith("W"):
        wave, gate = gate_id[1:].split(".", 1)
        return (100 + int(wave), int(gate), 0)
    match = re.fullmatch(r"([A-Z])(\d+)(?:\.(\d+))?", gate_id)
    if not match:  # pragma: no cover - guarded by the parser regexes
        raise ValueError(f"Unsupported gate id: {gate_id}")
    letter, major, minor = match.groups()
    return (ord(letter) - ord("A"), int(major), int(minor or 0))


def parse_plan(text: str) -> tuple[list[str], list[str], list[str]]:
    definitions: list[str] = []
    progress: list[str] = []
    hidden_ranges: list[str] = []

    for line in text.splitlines():
        for pattern in DEFINITION_PATTERNS:
            match = pattern.match(line)
            if match:
                definitions.append(match.group(1))
                break
        progress_match = PROGRESS_PATTERN.match(line)
        if progress_match:
            progress.append(progress_match.group(1))
        if line.startswith(("### ", "**")) and HIDDEN_RANGE_PATTERN.search(line):
            hidden_ranges.append(line.strip())

    return definitions, progress, hidden_ranges


def validate_plan(path: Path = DEFAULT_PLAN) -> list[str]:
    definitions, progress, hidden_ranges = parse_plan(
        path.read_text(encoding="utf-8")
    )
    errors: list[str] = []

    for label, values in (("definition", definitions), ("progress", progress)):
        duplicates = sorted(
            gate_id for gate_id, count in Counter(values).items() if count > 1
        )
        if duplicates:
            errors.append(f"Duplicate {label} ids: {', '.join(duplicates)}")

    missing_progress = sorted(set(definitions) - set(progress), key=_natural_key)
    if missing_progress:
        errors.append(
            f"Definitions missing progress rows: {', '.join(missing_progress)}"
        )

    undefined_progress = sorted(set(progress) - set(definitions), key=_natural_key)
    if undefined_progress:
        errors.append(
            f"Progress rows missing definitions: {', '.join(undefined_progress)}"
        )

    if progress != sorted(progress, key=_natural_key):
        errors.append("Progress rows are not ordered by gate id")

    if hidden_ranges:
        errors.append(
            "Hidden gate ranges are forbidden; define each gate explicitly: "
            + " | ".join(hidden_ranges)
        )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("plan", nargs="?", type=Path, default=DEFAULT_PLAN)
    args = parser.parse_args()
    errors = validate_plan(args.plan)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"VALID: {args.plan}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

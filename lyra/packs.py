"""Data-pack layout, frontmatter, and (later) runtime loading."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PACK_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_MARKDOWN = (
    "personality/system_prompt.md",
    "personality/character_bible.md",
    "personality/emotional_color_map.md",
    "personality/speech_and_idioms.md",
    "personality/appearance.md",
    "ship/ship_reference.md",
    "ship/systems.md",
    "ship/cargo_and_layout.md",
    "state/relationship.md",
    "state/active_arcs.md",
    "state/user_knowledge.md",
)

REQUIRED_JSON = (
    "ship/current_status.json",
    "state/relationship.json",
)

FRONTMATTER_KEYS = ("pack", "file", "version", "last_updated")

_PACK_FOR_PREFIX = {
    "personality": "personality",
    "ship": "ship",
    "state": "state",
}


def parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        raise ValueError("missing YAML frontmatter delimiter")
    end = text.find("\n---", 3)
    if end < 0:
        raise ValueError("unclosed YAML frontmatter")
    block = text[4:end]
    fields: dict[str, str] = {}
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise ValueError(f"invalid frontmatter line: {raw_line!r}")
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip()
    return fields


def validate_pack_layout(root: Path | None = None) -> list[str]:
    """Return human-readable errors; empty list means the layout is valid."""
    base = root if root is not None else PACK_ROOT
    errors: list[str] = []

    for relative in REQUIRED_MARKDOWN:
        path = base / relative
        if not path.is_file():
            errors.append(f"missing markdown pack file: {relative}")
            continue
        try:
            fields = parse_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            errors.append(f"{relative}: {exc}")
            continue
        missing = [key for key in FRONTMATTER_KEYS if not fields.get(key)]
        if missing:
            errors.append(f"{relative}: missing frontmatter keys {missing}")
            continue
        expected_pack = _PACK_FOR_PREFIX[relative.split("/", 1)[0]]
        if fields["pack"] != expected_pack:
            errors.append(
                f"{relative}: pack={fields['pack']!r} expected {expected_pack!r}"
            )
        expected_file = Path(relative).stem
        if fields["file"] != expected_file:
            errors.append(
                f"{relative}: file={fields['file']!r} expected {expected_file!r}"
            )

    for relative in REQUIRED_JSON:
        path = base / relative
        if not path.is_file():
            errors.append(f"missing JSON pack file: {relative}")
            continue
        try:
            payload: Any = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            errors.append(f"{relative}: {exc}")
            continue
        if not isinstance(payload, dict):
            errors.append(f"{relative}: expected a JSON object")

    return errors

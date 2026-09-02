"""Data-pack layout, validation, and runtime loading (ADR-003)."""

from __future__ import annotations

from dataclasses import dataclass
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

SHIP_STATUS_KEYS = ("overall_condition", "systems", "location", "living_conversion")
SHIP_STATUS_SYSTEMS = ("quantum_drive", "power_core", "stealth", "life_support", "hull")

STORY_CANON_DIR = "state/story"

# Former source-of-truth files kept as pointers. They must stay pointers:
# a second full copy is how the persona drifts (ADR-003).
LEGACY_POINTERS = {
    "agents/lyra/system_prompt.md": "personality/system_prompt.md",
    "agents/lyra/character_file.md": "personality/character_bible.md",
    "agents/lyra/references/appearance_reference.md": "personality/appearance.md",
    "agents/lyra/references/color_emotion_map.md": "personality/emotional_color_map.md",
    "agents/lyra/references/idiom_list.md": "personality/speech_and_idioms.md",
    "agents/lyra/references/personality_quirks.md": "personality/speech_and_idioms.md",
    "agents/lyra/references/ship_reference.md": "ship/ship_reference.md",
    "agents/lyra/state/relationship_state.md": "state/relationship.md",
    "agents/lyra/state/story/ship.md": "state/story/ship.md",
    "agents/lyra/state/story/arcs.md": "state/story/arcs.md",
    "agents/lyra/state/story/timeline.md": "state/story/timeline.md",
}

POINTER_MAX_CHARS = 600

_PACK_FOR_PREFIX = {
    "personality": "personality",
    "ship": "ship",
    "state": "state",
}


class PackError(RuntimeError):
    """Raised when the pack tree cannot be loaded safely."""


@dataclass(frozen=True)
class PackDocument:
    relative: str
    pack: str
    file: str
    version: str
    last_updated: str
    body: str


@dataclass(frozen=True)
class LyraPacks:
    root: Path
    documents: dict[str, PackDocument]
    ship_status: dict[str, Any]
    relationship: dict[str, Any]

    def document(self, relative: str) -> PackDocument:
        try:
            return self.documents[relative]
        except KeyError as exc:
            raise PackError(f"unknown pack document: {relative}") from exc

    def body(self, relative: str) -> str:
        return self.document(relative).body


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
        elif relative == "ship/current_status.json":
            errors.extend(_ship_status_errors(payload))

    errors.extend(_pointer_errors(base))

    return errors


def _pointer_errors(base: Path) -> list[str]:
    errors: list[str] = []
    for legacy, pack_path in LEGACY_POINTERS.items():
        path = base / legacy
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if pack_path not in text:
            errors.append(f"{legacy}: pointer does not name {pack_path}")
        if len(text) > POINTER_MAX_CHARS:
            errors.append(
                f"{legacy}: still holds full content ({len(text)} chars); "
                f"{pack_path} is the source of truth"
            )
    return errors


def _ship_status_errors(payload: dict[str, Any]) -> list[str]:
    errors = [
        f"ship/current_status.json: missing key {key!r}"
        for key in SHIP_STATUS_KEYS
        if key not in payload
    ]

    systems = payload.get("systems")
    if not isinstance(systems, dict):
        errors.append("ship/current_status.json: 'systems' must be an object")
        return errors

    for name in SHIP_STATUS_SYSTEMS:
        block = systems.get(name)
        if not isinstance(block, dict):
            errors.append(f"ship/current_status.json: missing system block {name!r}")
        elif not block.get("status"):
            errors.append(f"ship/current_status.json: system {name!r} has no status")

    return errors


def load_packs(root: Path | None = None) -> LyraPacks:
    """Validate and load the personality, ship, and state packs."""
    base = root if root is not None else PACK_ROOT
    errors = validate_pack_layout(base)
    if errors:
        raise PackError("invalid Lyra pack tree:\n" + "\n".join(errors))

    documents: dict[str, PackDocument] = {}
    for relative in REQUIRED_MARKDOWN:
        text = (base / relative).read_text(encoding="utf-8")
        fields = parse_frontmatter(text)
        body = text[text.find("\n---", 3) + 4 :].lstrip("\n")
        documents[relative] = PackDocument(
            relative=relative,
            pack=fields["pack"],
            file=fields["file"],
            version=fields["version"],
            last_updated=fields["last_updated"],
            body=body,
        )

    return LyraPacks(
        root=base,
        documents=documents,
        ship_status=json.loads(
            (base / "ship/current_status.json").read_text(encoding="utf-8")
        ),
        relationship=json.loads(
            (base / "state/relationship.json").read_text(encoding="utf-8")
        ),
    )


def compose_runtime_context(
    packs: LyraPacks | None = None,
    *,
    include_lore: bool = True,
    include_ship: bool = True,
    include_state: bool = True,
    root: Path | None = None,
) -> str:
    """Compose the persona context an agent runtime injects at session start."""
    loaded = packs if packs is not None else load_packs(root)

    sections = [
        loaded.body("personality/system_prompt.md"),
        loaded.body("personality/character_bible.md"),
    ]

    if include_lore:
        sections.extend(
            loaded.body(relative)
            for relative in (
                "personality/appearance.md",
                "personality/emotional_color_map.md",
                "personality/speech_and_idioms.md",
            )
        )

    if include_ship:
        sections.append(loaded.body("ship/ship_reference.md"))
        sections.append(
            "# Ship Status (live)\n\n"
            f"- Overall condition: {loaded.ship_status['overall_condition']}\n"
            f"- Last updated: {loaded.ship_status.get('last_updated', 'unknown')}"
        )

    if include_state:
        sections.extend(
            loaded.body(relative)
            for relative in (
                "state/relationship.md",
                "state/active_arcs.md",
                "state/user_knowledge.md",
            )
        )

    return "\n\n---\n\n".join(section.strip() for section in sections) + "\n"

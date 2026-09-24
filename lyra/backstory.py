"""W9.2 backstory source accounting, ownership, and review validation."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any

from lyra.packs import PACK_ROOT, parse_frontmatter

DEFAULT_MAP = PACK_ROOT / "agents/lyra/references/backstory_map.json"
BACKSTORY_INDEX = "agents/lyra/references/backstory.md"
TOPIC_GLOB = "backstory_*.md"

SOURCE_DISPOSITIONS = {"imported", "pending_review", "context_only"}
CANON_STATUSES = {"approved_existing", "candidate", "rejected"}
REVIEW_STATUSES = {"pending", "approved", "rejected"}


class BackstoryMapError(RuntimeError):
    """Raised when W9.2 source accounting or topic routing is invalid."""


@dataclass(frozen=True)
class BackstoryMap:
    root: Path
    payload: dict[str, Any]

    @property
    def pending_reviews(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            item
            for item in self.payload["review_items"]
            if item["status"] == "pending"
        )

    @property
    def approved_topic_paths(self) -> tuple[str, ...]:
        return tuple(
            topic["path"]
            for topic in self.payload["topics"]
            if topic["canon_status"] == "approved_existing"
        )


def _repo_path(root: Path, value: Any, label: str, errors: list[str]) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{label}: path is missing")
        return None
    if "\\" in value:
        errors.append(f"{label}: path must use repository-relative forward slashes")
        return None
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts:
        errors.append(f"{label}: path escapes the repository: {value!r}")
        return None
    return root.joinpath(*pure.parts)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _list_field(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def validate_backstory_map(
    map_path: Path = DEFAULT_MAP, *, root: Path | None = None
) -> list[str]:
    """Return deterministic W9.2 validation errors; an empty list is valid."""
    base = root if root is not None else PACK_ROOT
    errors: list[str] = []

    try:
        payload = json.loads(map_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"backstory map cannot be read: {exc}"]
    if not isinstance(payload, dict):
        return ["backstory map must be a JSON object"]

    for field in ("version", "gate", "status", "sources", "topics", "review_items"):
        if field not in payload:
            errors.append(f"backstory map missing field: {field}")
    if errors:
        return errors
    if payload["gate"] != "W9.2":
        errors.append("backstory map gate must be W9.2")

    sources = payload["sources"]
    topics = payload["topics"]
    reviews = payload["review_items"]
    if not isinstance(sources, list) or not isinstance(topics, list) or not isinstance(reviews, list):
        return errors + ["sources, topics, and review_items must be arrays"]

    source_ids: set[str] = set()
    for position, source in enumerate(sources):
        label = f"sources[{position}]"
        if not isinstance(source, dict):
            errors.append(f"{label}: expected object")
            continue
        source_id = source.get("source_id")
        if not isinstance(source_id, str) or not source_id:
            errors.append(f"{label}: source_id is missing")
            continue
        if source_id in source_ids:
            errors.append(f"duplicate source_id: {source_id}")
        source_ids.add(source_id)
        if source.get("disposition") not in SOURCE_DISPOSITIONS:
            errors.append(f"{source_id}: invalid disposition")
        for field in ("source_type", "origin_commit", "source_date", "sha256", "notes"):
            if not source.get(field):
                errors.append(f"{source_id}: missing {field}")
        path = _repo_path(base, source.get("path"), source_id, errors)
        if path is None:
            continue
        if not path.is_file():
            errors.append(f"{source_id}: missing source file {source.get('path')}")
            continue
        expected_hash = source.get("sha256")
        if isinstance(expected_hash, str) and _sha256(path) != expected_hash:
            errors.append(f"{source_id}: SHA-256 does not match {source.get('path')}")

    review_ids: set[str] = set()
    pending_count = 0
    for position, review in enumerate(reviews):
        label = f"review_items[{position}]"
        if not isinstance(review, dict):
            errors.append(f"{label}: expected object")
            continue
        review_id = review.get("review_id")
        if not isinstance(review_id, str) or not review_id:
            errors.append(f"{label}: review_id is missing")
            continue
        if review_id in review_ids:
            errors.append(f"duplicate review_id: {review_id}")
        review_ids.add(review_id)
        status = review.get("status")
        if status not in REVIEW_STATUSES:
            errors.append(f"{review_id}: invalid review status")
        if status == "pending":
            pending_count += 1
        for field in ("kind", "claim", "conflict", "recommendation"):
            if not review.get(field):
                errors.append(f"{review_id}: missing {field}")
        linked_sources = review.get("source_ids")
        if not isinstance(linked_sources, list) or not linked_sources:
            errors.append(f"{review_id}: source_ids must be a non-empty array")
        else:
            for source_id in linked_sources:
                if source_id not in source_ids:
                    errors.append(f"{review_id}: unknown source_id {source_id}")

    topic_ids: set[str] = set()
    topic_paths: set[str] = set()
    for position, topic in enumerate(topics):
        label = f"topics[{position}]"
        if not isinstance(topic, dict):
            errors.append(f"{label}: expected object")
            continue
        reference_id = topic.get("reference_id")
        relative = topic.get("path")
        if not isinstance(reference_id, str) or not reference_id:
            errors.append(f"{label}: reference_id is missing")
            continue
        if reference_id in topic_ids:
            errors.append(f"duplicate reference_id: {reference_id}")
        topic_ids.add(reference_id)
        if relative in topic_paths:
            errors.append(f"duplicate topic path: {relative}")
        if isinstance(relative, str):
            topic_paths.add(relative)
        if topic.get("canon_status") not in CANON_STATUSES:
            errors.append(f"{reference_id}: invalid canon_status")
        if topic.get("owner") != "agents/lyra/references":
            errors.append(f"{reference_id}: invalid owner")
        linked_sources = topic.get("source_ids")
        if not isinstance(linked_sources, list) or not linked_sources:
            errors.append(f"{reference_id}: source_ids must be a non-empty array")
        else:
            for source_id in linked_sources:
                if source_id not in source_ids:
                    errors.append(f"{reference_id}: unknown source_id {source_id}")
        linked_reviews = topic.get("review_ids", [])
        if not isinstance(linked_reviews, list):
            errors.append(f"{reference_id}: review_ids must be an array")
            linked_reviews = []
        for review_id in linked_reviews:
            if review_id not in review_ids:
                errors.append(f"{reference_id}: unknown review_id {review_id}")

        path = _repo_path(base, relative, reference_id, errors)
        if path is None or not path.is_file():
            if path is not None:
                errors.append(f"{reference_id}: missing topic file {relative}")
            continue
        try:
            fields = parse_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            errors.append(f"{reference_id}: invalid frontmatter: {exc}")
            continue
        expected = {
            "reference_id": reference_id,
            "canon_status": topic.get("canon_status"),
            "owner": topic.get("owner"),
        }
        for field, value in expected.items():
            if fields.get(field) != value:
                errors.append(
                    f"{reference_id}: frontmatter {field}={fields.get(field)!r}, expected {value!r}"
                )
        if set(_list_field(fields.get("source_ids"))) != set(linked_sources or []):
            errors.append(f"{reference_id}: frontmatter source_ids do not match map")
        if set(_list_field(fields.get("review_ids"))) != set(linked_reviews):
            errors.append(f"{reference_id}: frontmatter review_ids do not match map")

    reference_dir = base / "agents/lyra/references"
    active_topics = {
        path.relative_to(base).as_posix()
        for path in reference_dir.glob(TOPIC_GLOB)
        if path.name != "backstory_map.json"
    }
    for missing in sorted(active_topics - topic_paths):
        errors.append(f"unregistered backstory topic: {missing}")
    for missing in sorted(topic_paths - active_topics):
        errors.append(f"mapped path is not an active backstory topic: {missing}")

    index_path = base / BACKSTORY_INDEX
    if not index_path.is_file():
        errors.append(f"missing backstory index: {BACKSTORY_INDEX}")
    else:
        index = index_path.read_text(encoding="utf-8")
        if len(index) > 1600:
            errors.append("backstory index has regrown into a duplicate source of truth")
        for relative in topic_paths:
            if Path(relative).name not in index:
                errors.append(f"backstory index does not link {relative}")
        if "## Origin" in index or "## The Escape" in index:
            errors.append("backstory index duplicates topic content")

    expected_status = "awaiting_human_review" if pending_count else "approved"
    if payload.get("status") != expected_status:
        errors.append(
            f"backstory map status must be {expected_status!r} with {pending_count} pending reviews"
        )
    return errors


def load_backstory_map(
    map_path: Path = DEFAULT_MAP, *, root: Path | None = None
) -> BackstoryMap:
    base = root if root is not None else PACK_ROOT
    errors = validate_backstory_map(map_path, root=base)
    if errors:
        raise BackstoryMapError("invalid backstory map:\n" + "\n".join(errors))
    payload = json.loads(map_path.read_text(encoding="utf-8"))
    return BackstoryMap(root=base, payload=payload)

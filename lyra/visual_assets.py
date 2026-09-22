"""Machine-readable visual-reference catalog validation.

The catalog is deliberately fail-closed: a file may be useful as a local
reference while still being ineligible for canon promotion or transmission to
an external renderer.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LIBRARY_ROOT = ROOT / "assets" / "visual_references"
DEFAULT_CATALOG = DEFAULT_LIBRARY_ROOT / "catalog.json"
DEFAULT_ANCHOR_MANIFEST = (
    DEFAULT_LIBRARY_ROOT / "lyra" / "approved" / "canonical_anchors.json"
)

IMAGE_EXTENSIONS = {".gif", ".jpeg", ".jpg", ".png", ".webp"}
SUBJECTS = {"location", "lyra", "prop", "ship", "wardrobe"}
CANON_STATUSES = {"approved", "candidate", "reference"}
APPROVAL_STATUSES = {"approved", "not_required", "pending", "rejected"}
RIGHTS_STATUSES = {"cleared", "restricted", "unknown_pending_review"}
ID_PATTERN = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)+$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
REMOTE_URL_PATTERN = re.compile(r"https?://", re.IGNORECASE)
SENSITIVE_KEY_PATTERN = re.compile(
    r"(?:api[_-]?key|access[_-]?token|password|credential|secret)", re.IGNORECASE
)

REQUIRED_ASSET_FIELDS = {
    "asset_id",
    "path",
    "sha256",
    "lifecycle_status",
    "subject",
    "subject_id",
    "canon_status",
    "approval",
    "provenance",
    "usage_rights",
    "allowed_transformations",
    "visual_traits",
    "supersession",
    "approved_for_external_renderer",
    "review_item_ids",
}


def load_catalog(path: Path = DEFAULT_CATALOG) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _walk_values(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    values: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            values.append((child_prefix, child))
            values.extend(_walk_values(child, child_prefix))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            values.extend(_walk_values(child, f"{prefix}[{index}]"))
    return values


def _cataloged_images(library_root: Path) -> set[str]:
    return {
        path.relative_to(library_root).as_posix()
        for path in library_root.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    }


def validate_catalog_data(
    catalog: dict[str, Any],
    *,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    anchor_manifest: Path = DEFAULT_ANCHOR_MANIFEST,
) -> list[str]:
    errors: list[str] = []
    if catalog.get("schema_version") != 1:
        errors.append("catalog.schema_version must be 1")
    if catalog.get("library_root") != "assets/visual_references":
        errors.append("catalog.library_root must be assets/visual_references")

    assets = catalog.get("assets")
    if not isinstance(assets, list):
        return errors + ["catalog.assets must be a list"]
    reviews = catalog.get("review_items")
    if not isinstance(reviews, list):
        return errors + ["catalog.review_items must be a list"]

    review_ids: list[str] = []
    for index, review in enumerate(reviews):
        label = f"review_items[{index}]"
        if not isinstance(review, dict):
            errors.append(f"{label} must be an object")
            continue
        review_id = review.get("review_id")
        if not isinstance(review_id, str) or not ID_PATTERN.fullmatch(review_id):
            errors.append(f"{label}.review_id is invalid")
        else:
            review_ids.append(review_id)
        if review.get("kind") not in {
            "approval",
            "canon_conflict",
            "duplicate",
            "provenance",
        }:
            errors.append(f"{label}.kind is invalid")
        if not isinstance(review.get("asset_ids"), list):
            errors.append(f"{label}.asset_ids must be a list")
        if review.get("status") not in {"pending_human", "resolved"}:
            errors.append(f"{label}.status is invalid")
        if review.get("status") == "resolved" and not review.get("decision"):
            errors.append(f"{label} resolved without a decision")
        if review.get("status") == "pending_human" and review.get("decision") is not None:
            errors.append(f"{label} pending_human must have a null decision")
    duplicate_review_ids = sorted(
        item for item, count in Counter(review_ids).items() if count > 1
    )
    if duplicate_review_ids:
        errors.append(f"duplicate review IDs: {', '.join(duplicate_review_ids)}")
    review_id_set = set(review_ids)

    asset_ids: list[str] = []
    paths: list[str] = []
    hashes: defaultdict[str, list[str]] = defaultdict(list)
    assets_by_id: dict[str, dict[str, Any]] = {}

    for index, asset in enumerate(assets):
        label = f"assets[{index}]"
        if not isinstance(asset, dict):
            errors.append(f"{label} must be an object")
            continue
        missing = sorted(REQUIRED_ASSET_FIELDS - set(asset))
        if missing:
            errors.append(f"{label} missing fields: {', '.join(missing)}")
            continue

        asset_id = asset["asset_id"]
        if not isinstance(asset_id, str) or not ID_PATTERN.fullmatch(asset_id):
            errors.append(f"{label}.asset_id is invalid")
            asset_id = f"<invalid:{index}>"
        else:
            asset_ids.append(asset_id)
            assets_by_id[asset_id] = asset
        item_label = f"asset {asset_id}"

        relative = asset["path"]
        if not isinstance(relative, str):
            errors.append(f"{item_label} path must be a string")
        else:
            pure_path = PurePosixPath(relative)
            if (
                pure_path.is_absolute()
                or ".." in pure_path.parts
                or "\\" in relative
                or pure_path.suffix.lower() not in IMAGE_EXTENSIONS
            ):
                errors.append(f"{item_label} has unsafe or unsupported path: {relative}")
            else:
                paths.append(relative)
                full_path = library_root / Path(*pure_path.parts)
                if not full_path.is_file():
                    errors.append(f"{item_label} file is missing: {relative}")
                elif not SHA256_PATTERN.fullmatch(str(asset["sha256"])):
                    errors.append(f"{item_label} sha256 is invalid")
                else:
                    actual_hash = _sha256(full_path)
                    if actual_hash != asset["sha256"]:
                        errors.append(
                            f"{item_label} sha256 mismatch: {asset['sha256']} != {actual_hash}"
                        )
                    hashes[asset["sha256"]].append(asset_id)

        if asset["lifecycle_status"] not in {"active", "superseded"}:
            errors.append(f"{item_label} lifecycle_status is invalid")
        if asset["subject"] not in SUBJECTS:
            errors.append(f"{item_label} has invalid subject: {asset['subject']}")
        if not isinstance(asset["subject_id"], str) or not ID_PATTERN.fullmatch(
            asset["subject_id"]
        ):
            errors.append(f"{item_label} subject_id is invalid")
        if asset["subject"] == "location" and not asset.get("location_id"):
            errors.append(f"{item_label} location subject requires location_id")
        if asset["subject"] != "location" and "location_id" in asset:
            errors.append(f"{item_label} non-location asset must not define location_id")

        canon_status = asset["canon_status"]
        if canon_status not in CANON_STATUSES:
            errors.append(f"{item_label} canon_status is invalid")
        approval = asset["approval"]
        if not isinstance(approval, dict) or approval.get("status") not in APPROVAL_STATUSES:
            errors.append(f"{item_label} approval status is invalid")
        elif canon_status == "approved":
            if approval.get("status") != "approved":
                errors.append(f"{item_label} is canonical without human approval")
            for field in ("decided_by", "decided_at"):
                if not approval.get(field):
                    errors.append(f"{item_label} approved without {field}")
        elif canon_status == "candidate" and approval.get("status") != "pending":
            errors.append(f"{item_label} candidate approval must be pending")
        elif canon_status == "reference" and approval.get("status") != "not_required":
            errors.append(f"{item_label} reference approval must be not_required")

        provenance = asset["provenance"]
        rights = asset["usage_rights"]
        if not isinstance(provenance, dict) or not provenance.get("source_type"):
            errors.append(f"{item_label} provenance is incomplete")
        if not isinstance(rights, dict) or rights.get("status") not in RIGHTS_STATUSES:
            errors.append(f"{item_label} usage_rights is invalid")
        if not isinstance(asset["allowed_transformations"], list):
            errors.append(f"{item_label} allowed_transformations must be a list")
        if not isinstance(asset["visual_traits"], dict) or not asset[
            "visual_traits"
        ].get("crop"):
            errors.append(f"{item_label} visual_traits.crop is required")
        supersession = asset["supersession"]
        if not isinstance(supersession, dict):
            errors.append(f"{item_label} supersession must be an object")
        elif not isinstance(supersession.get("supersedes"), list):
            errors.append(f"{item_label} supersession.supersedes must be a list")
        if not isinstance(asset["approved_for_external_renderer"], bool):
            errors.append(f"{item_label} external-renderer flag must be boolean")
        elif asset["approved_for_external_renderer"]:
            if canon_status != "approved" or rights.get("status") != "cleared":
                errors.append(
                    f"{item_label} cannot leave the workstation without approved canon and cleared rights"
                )
        if rights.get("status") != "cleared" and asset["allowed_transformations"]:
            errors.append(
                f"{item_label} transformations must stay empty until rights are cleared"
            )
        if canon_status == "candidate" and not str(asset["path"]).startswith(
            "lyra/candidates/"
        ):
            errors.append(f"{item_label} candidate is outside lyra/candidates")
        if canon_status == "approved" and not str(asset["path"]).startswith(
            "lyra/approved/"
        ):
            errors.append(f"{item_label} approved canon is outside lyra/approved")

        linked_reviews = asset["review_item_ids"]
        if not isinstance(linked_reviews, list):
            errors.append(f"{item_label} review_item_ids must be a list")
        else:
            unknown = sorted(set(linked_reviews) - review_id_set)
            if unknown:
                errors.append(
                    f"{item_label} references unknown reviews: {', '.join(unknown)}"
                )

        for key_path, value in _walk_values(asset):
            if SENSITIVE_KEY_PATTERN.search(key_path):
                errors.append(f"{item_label} contains prohibited credential field: {key_path}")
            if isinstance(value, str) and REMOTE_URL_PATTERN.search(value):
                errors.append(f"{item_label} contains a committed remote URL: {key_path}")

    duplicate_ids = sorted(item for item, count in Counter(asset_ids).items() if count > 1)
    if duplicate_ids:
        errors.append(f"duplicate asset IDs: {', '.join(duplicate_ids)}")
    duplicate_paths = sorted(item for item, count in Counter(paths).items() if count > 1)
    if duplicate_paths:
        errors.append(f"duplicate catalog paths: {', '.join(duplicate_paths)}")
    for digest, digest_asset_ids in sorted(hashes.items()):
        if len(digest_asset_ids) > 1:
            errors.append(
                f"duplicate file content ({digest}): {', '.join(sorted(digest_asset_ids))}"
            )

    disk_images = _cataloged_images(library_root)
    catalog_paths = set(paths)
    missing_metadata = sorted(disk_images - catalog_paths)
    missing_files = sorted(catalog_paths - disk_images)
    if missing_metadata:
        errors.append(f"active image files missing catalog metadata: {', '.join(missing_metadata)}")
    if missing_files:
        errors.append(f"catalog paths missing image files: {', '.join(missing_files)}")

    for asset in assets:
        if not isinstance(asset, dict) or "asset_id" not in asset:
            continue
        supersession = asset.get("supersession", {})
        linked = list(supersession.get("supersedes", []))
        if supersession.get("superseded_by"):
            linked.append(supersession["superseded_by"])
        if supersession.get("variant_of"):
            linked.append(supersession["variant_of"])
        unknown_assets = sorted(set(linked) - set(assets_by_id))
        if unknown_assets:
            errors.append(
                f"asset {asset['asset_id']} has unknown supersession IDs: "
                + ", ".join(unknown_assets)
            )
        base_id = supersession.get("variant_of")
        if asset.get("canon_status") == "approved" and base_id:
            base = assets_by_id.get(base_id)
            if base and base.get("canon_status") != "approved":
                errors.append(
                    f"asset {asset['asset_id']} variant cannot be approved before {base_id}"
                )

    known_asset_ids = set(assets_by_id)
    for review in reviews:
        if not isinstance(review, dict) or not isinstance(review.get("asset_ids"), list):
            continue
        unknown_assets = sorted(set(review["asset_ids"]) - known_asset_ids)
        if unknown_assets:
            errors.append(
                f"review {review.get('review_id', '<invalid>')} references unknown assets: "
                + ", ".join(unknown_assets)
            )

    if anchor_manifest.is_file():
        manifest = json.loads(anchor_manifest.read_text(encoding="utf-8"))
        manifest_dir = anchor_manifest.parent
        for anchor in manifest.get("anchors", []):
            anchor_id = anchor.get("asset_id")
            asset = assets_by_id.get(anchor_id)
            if not asset:
                errors.append(f"anchor manifest asset missing from catalog: {anchor_id}")
                continue
            try:
                expected_path = (
                    (manifest_dir / anchor.get("file", "")).resolve()
                    .relative_to(library_root.resolve())
                    .as_posix()
                )
            except (TypeError, ValueError):
                errors.append(f"anchor {anchor_id} has an unsafe file path")
                continue
            if asset.get("path") != expected_path:
                errors.append(
                    f"anchor {anchor_id} path mismatch: {asset.get('path')} != {expected_path}"
                )
            if asset.get("sha256") != anchor.get("sha256"):
                errors.append(f"anchor {anchor_id} hash disagrees with manifest")
            for source in anchor.get("primary_sources", []) + anchor.get(
                "supporting_sources", []
            ):
                if not (manifest_dir / source).resolve().is_file():
                    errors.append(f"anchor {anchor_id} source is missing: {source}")
    else:
        errors.append(f"anchor manifest is missing: {anchor_manifest}")
    return errors


def validate_catalog(path: Path = DEFAULT_CATALOG) -> list[str]:
    try:
        catalog = load_catalog(path)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot load catalog {path}: {exc}"]
    return validate_catalog_data(catalog, library_root=path.parent)

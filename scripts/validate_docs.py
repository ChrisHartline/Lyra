"""Validate documentation links and high-value freshness invariants."""

from __future__ import annotations

import os
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {
    ".agents",
    ".claude",
    ".codex",
    ".cursor",
    ".git",
    ".pytest_cache",
    "__pycache__",
    "backups",
    "data",
    "node_modules",
    "venv",
}
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


def _markdown_files() -> list[Path]:
    files: list[Path] = []
    for current, directories, names in os.walk(ROOT):
        directories[:] = [name for name in directories if name not in SKIP_DIRS]
        base = Path(current)
        files.extend(base / name for name in names if name.endswith(".md"))
    return sorted(files)


def _check_links(files: list[Path]) -> list[str]:
    errors: list[str] = []
    for path in files:
        content = path.read_text(encoding="utf-8")
        for match in MARKDOWN_LINK.finditer(content):
            target = match.group(1).strip().strip("<>")
            if not target or re.match(r"^(?:https?://|mailto:|#)", target):
                continue
            relative = target.split("#", 1)[0]
            resolved = (path.parent / relative).resolve()
            if not resolved.exists():
                errors.append(
                    f"broken link in {path.relative_to(ROOT)}: {target}"
                )
    return errors


def _first_not_started_gate(build_plan: str) -> str | None:
    for match in re.finditer(
        r"^\|\s*(W\d+\.\d+)\s*\|\s*([^|]+?)\s*\|", build_plan, re.MULTILINE
    ):
        if match.group(2).strip() == "Not started":
            return match.group(1)
    return None


def validate_documentation() -> list[str]:
    errors = _check_links(_markdown_files())
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    srs = (ROOT / "docs" / "lyra_system_requirements.md").read_text(
        encoding="utf-8"
    )
    build_plan = (ROOT / "docs" / "lyra_build_plan.md").read_text(
        encoding="utf-8"
    )
    schema = (ROOT / "db" / "schema.sql").read_text(encoding="utf-8")
    workstation = (ROOT / "docs" / "workstation_service.md").read_text(
        encoding="utf-8"
    )

    srs_version = re.search(r"^\*\*Version:\*\*\s*([^\s]+)", srs, re.MULTILINE)
    companion = re.search(r"\(SRS v([^\)]+)\)", build_plan)
    if not srs_version or not companion:
        errors.append("SRS/build-plan version declarations are missing")
    elif srs_version.group(1) != companion.group(1):
        errors.append(
            "SRS/build-plan version mismatch: "
            f"{srs_version.group(1)} != {companion.group(1)}"
        )
    if srs_version and f"SRS v{srs_version.group(1)}" not in readme:
        errors.append("README current SRS version is stale")

    next_gate = _first_not_started_gate(build_plan)
    if next_gate and next_gate not in readme:
        errors.append(f"README does not identify the next gate ({next_gate})")

    schema_tables = len(re.findall(r"^CREATE TABLE IF NOT EXISTS\s+", schema, re.M))
    documented_tables = re.search(
        r"covers all\s+(\d+)\s+required tables", workstation, re.I
    )
    if not documented_tables or int(documented_tables.group(1)) != schema_tables:
        errors.append(
            "workstation guide table count is stale: "
            f"documented={documented_tables.group(1) if documented_tables else 'missing'} "
            f"schema={schema_tables}"
        )

    scripts_readme = (ROOT / "scripts" / "README.md").read_text(encoding="utf-8")
    for path in sorted((ROOT / "scripts").iterdir()):
        if path.is_file() and path.name != "README.md" and path.name not in scripts_readme:
            errors.append(f"scripts/README.md does not mention {path.name}")

    mcp_readme = (ROOT / "mcp" / "README.md").read_text(encoding="utf-8")
    for folder, pattern in (("server", "*.py"), ("tools", "*.md")):
        for path in sorted((ROOT / "mcp" / folder).glob(pattern)):
            if path.name == "__init__.py":
                continue
            relative = path.relative_to(ROOT / "mcp").as_posix()
            if relative not in mcp_readme:
                errors.append(f"mcp/README.md does not mention {relative}")
    return errors


def main() -> int:
    errors = validate_documentation()
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("VALID: documentation links and freshness invariants")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

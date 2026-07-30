from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_KEYS = ("name", "description", "model")
ALLOWED_KEYS = REQUIRED_KEYS + ("readonly", "is_background")


@dataclass
class ValidationResult:
    file: Path
    valid: bool
    missing: list[str]


def parse_frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if len(lines) < 3 or lines[0].strip() != "---":
        return {}
    data: dict[str, str] = {}
    i = 1
    closed = False
    while i < len(lines) and lines[i].strip() != "---":
        line = lines[i]
        if ":" in line:
            k, v = line.split(":", 1)
            data[k.strip()] = v.strip()
        i += 1
    if i < len(lines) and lines[i].strip() == "---":
        closed = True
    return data if closed else {}


def validate_subagent(path: Path) -> ValidationResult:
    fm = parse_frontmatter(path.read_text(encoding="utf-8"))
    issues = [k for k in REQUIRED_KEYS if not fm.get(k)]
    issues.extend(f"unsupported:{key}" for key in fm if key not in ALLOWED_KEYS)
    if fm.get("name") and fm["name"] != path.stem:
        issues.append(f"name-mismatch:{fm['name']}!={path.stem}")
    for key in ("readonly", "is_background"):
        if key in fm and fm[key].lower() not in {"true", "false"}:
            issues.append(f"invalid-boolean:{key}")
    return ValidationResult(path, len(issues) == 0, issues)


def sync(
    src: Path | None = None,
    dst: Path | None = None,
    *,
    check: bool = False,
) -> list[ValidationResult]:
    src = src or ROOT / "agents/lyra/subagents"
    dst = dst or ROOT / ".cursor/agents"
    dst.mkdir(parents=True, exist_ok=True)
    results: list[ValidationResult] = []
    source_files = sorted(src.glob("*.md"))
    source_names = {file.name for file in source_files}

    for stale in sorted(dst.glob("*.md")):
        if stale.name in source_names:
            continue
        if check:
            results.append(ValidationResult(stale, False, ["stale-destination"]))
        else:
            stale.unlink()

    for file in source_files:
        result = validate_subagent(file)
        results.append(result)
        copied = dst / file.name
        if not result.valid:
            if copied.exists() and not check:
                copied.unlink()
            continue
        if check:
            if not copied.exists():
                result.valid = False
                result.missing.append("missing-destination")
            elif file.read_bytes() != copied.read_bytes():
                result.valid = False
                result.missing.append("out-of-sync")
        else:
            shutil.copy2(file, copied)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and sync Lyra subagents.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate byte identity without changing .cursor/agents.",
    )
    args = parser.parse_args()

    results = sync(check=args.check)
    bad = [r for r in results if not r.valid]
    for r in results:
        if r.valid:
            print(f"VALID: {r.file}")
        else:
            print(f"INVALID: {r.file} issues={','.join(r.missing)}")
    if bad:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

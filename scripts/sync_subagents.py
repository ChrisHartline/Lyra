from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil

REQUIRED_KEYS = ("name", "description", "model")


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
    while i < len(lines) and lines[i].strip() != "---":
        line = lines[i]
        if ":" in line:
            k, v = line.split(":", 1)
            data[k.strip()] = v.strip()
        i += 1
    return data


def validate_subagent(path: Path) -> ValidationResult:
    fm = parse_frontmatter(path.read_text(encoding="utf-8"))
    missing = [k for k in REQUIRED_KEYS if not fm.get(k)]
    return ValidationResult(path, len(missing) == 0, missing)


def sync() -> list[ValidationResult]:
    src = Path("agents/lyra/subagents")
    dst = Path(".cursor/agents")
    dst.mkdir(parents=True, exist_ok=True)
    results: list[ValidationResult] = []
    for file in sorted(src.glob("*.md")):
        result = validate_subagent(file)
        results.append(result)
        if not result.valid:
            continue
        shutil.copy2(file, dst / file.name)
    return results


def main() -> None:
    results = sync()
    bad = [r for r in results if not r.valid]
    for r in results:
        if r.valid:
            print(f"VALID: {r.file}")
        else:
            print(f"INVALID: {r.file} missing={','.join(r.missing)}")
    if bad:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

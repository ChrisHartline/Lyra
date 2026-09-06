from __future__ import annotations

import argparse
from pathlib import Path
import secrets


KEY = "LYRA_CONTROL_TOKEN"


def configure(env_path: Path, *, rotate: bool = False) -> bool:
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    existing = next(
        (
            line.split("=", 1)[1].strip()
            for line in lines
            if line.startswith(f"{KEY}=") and "=" in line
        ),
        "",
    )
    if existing and not rotate:
        return False
    retained = [line for line in lines if not line.startswith(f"{KEY}=")]
    retained.append(f"{KEY}={secrets.token_urlsafe(32)}")
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("\n".join(retained) + "\n", encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Configure Lyra's local memory-control token without printing it"
    )
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--rotate", action="store_true")
    args = parser.parse_args(argv)
    changed = configure(args.env_file, rotate=args.rotate)
    print(
        "Control token configured in .env; restart Lyra."
        if changed
        else "Control token already configured; no change."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

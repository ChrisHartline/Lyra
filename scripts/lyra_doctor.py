"""Print Lyra workstation-service capability status without exposing secrets."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

from lyra.service import capability_report, render_capability_report


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    load_dotenv(ROOT / ".env", override=False)
    capabilities = capability_report(repo_root=ROOT)
    print(render_capability_report(capabilities))
    required = {"runtime", "database", "conversation-model", "logging"}
    return int(
        any(
            item.name in required
            and item.state in {"unavailable", "unconfigured"}
            for item in capabilities
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())

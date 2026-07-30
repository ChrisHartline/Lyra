"""Generate a Lyra daily or weekly Notion digest (D2).

Usage:
  venv\\Scripts\\python scripts/generate_digest.py daily
  venv\\Scripts\\python scripts/generate_digest.py weekly
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lyra.config import settings
from lyra.digests import DigestService
from lyra.notion_sync import NotionClient


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish a Lyra daily or weekly digest to Notion.")
    parser.add_argument("period", choices=("daily", "weekly"))
    parser.add_argument(
        "--no-gather",
        action="store_true",
        help="Skip live corpus/memory/task gathering (empty source sections).",
    )
    args = parser.parse_args()

    if not settings.notion_token:
        print("FAIL: Notion token missing (NOTION_TOKEN / NOTION_API_KEY)")
        return 1
    if not settings.notion_digests_database_id:
        print("FAIL: LYRA_NOTION_DIGESTS_DATABASE_ID not set")
        return 2

    publisher = NotionClient(token=settings.notion_token)
    service = DigestService(
        publisher=publisher,
        digests_database_id=settings.notion_digests_database_id,
        title_property=settings.notion_digest_title_property,
        tasks_database_id=settings.notion_tasks_database_id,
        task_title_property=settings.notion_task_title_property,
    )
    result = service.publish(args.period, gather=not args.no_gather)
    print(f"published digest_id={result['digest_id']} type={result['digest_type']}")
    print(f"title={result['title']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

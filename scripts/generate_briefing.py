"""Assemble and optionally publish a Lyra assistant briefing (D5).

Usage:
  venv\\Scripts\\python scripts/generate_briefing.py morning
  venv\\Scripts\\python scripts/generate_briefing.py weekly --publish
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lyra.briefings import BriefingService
from lyra.config import settings
from lyra.notion_sync import NotionClient


def main() -> int:
    parser = argparse.ArgumentParser(description="Assemble a Lyra morning/weekly briefing.")
    parser.add_argument("period", choices=("morning", "weekly"))
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Publish the Notion-safe briefing to Digests DB",
    )
    args = parser.parse_args()

    publisher = None
    if args.publish:
        if not settings.notion_token or not settings.notion_digests_database_id:
            print("FAIL: Notion token and LYRA_NOTION_DIGESTS_DATABASE_ID required to publish")
            return 1
        publisher = NotionClient(token=settings.notion_token)

    service = BriefingService(
        digests_database_id=settings.notion_digests_database_id or "unset",
        title_property=settings.notion_digest_title_property,
        kg_memory_file=settings.kg_memory_file_path,
        publisher=publisher,
    )

    if args.publish:
        digest_type = "weekly" if args.period == "weekly" else "daily"
        result = service.publish_to_notion(args.period, digest_type=digest_type)
        print(f"published digest_id={result['digest_id']} type={result['digest_type']}")
    else:
        result = service.assemble(args.period, gather=True, for_notion=False)

    print(result["body"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Ensure a dedicated Lyra Digests Notion database exists.

Usage:
  venv\\Scripts\\python scripts/notion_ensure_digests_db.py

Requires NOTION_* token and LYRA_NOTION_PARENT_PAGE_ID (a normal Notion page,
not a database). Writes the new DB id to stdout for .env.
"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env", override=True)

from lyra.config import settings
from lyra.notion_sync import NotionClient


def main() -> int:
    if not settings.notion_token:
        print("FAIL: Notion token missing (NOTION_TOKEN / NOTION_API_KEY)")
        return 1
    parent = settings.notion_parent_page_id
    if not parent:
        print("FAIL: set LYRA_NOTION_PARENT_PAGE_ID to a page that can own the Digests DB")
        print("Tip: open any workspace page → Copy link → use its page UUID.")
        return 2

    client = NotionClient(token=settings.notion_token)
    db = client.ensure_digests_database(parent_page_id=parent)
    db_id = db["id"]
    print(f"digests_database_id={db_id}")
    print("Add to .env:")
    print(f"LYRA_NOTION_DIGESTS_DATABASE_ID={db_id}")
    print("LYRA_NOTION_DIGEST_TITLE_PROPERTY=Name")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

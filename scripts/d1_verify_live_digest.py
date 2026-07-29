"""D1 — live verification: a research digest lands in Digests, never Projects.

Live e2e per the build plan: creates a Digests row (Type=research) against
the real Notion workspace, and proves the Projects/tasks database row count
is unchanged by the write (i.e. digests never leak into the tasks board).

Usage:
  venv\\Scripts\\python scripts/d1_verify_live_digest.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lyra.config import settings
from lyra.notion_sync import NotionClient


def main() -> int:
    if not settings.notion_token:
        print("FAIL: Notion token not set (NOTION_TOKEN / NOTION_API_KEY)")
        return 1
    if not settings.notion_digests_database_id:
        print("FAIL: LYRA_NOTION_DIGESTS_DATABASE_ID not set")
        return 2
    if not settings.notion_tasks_database_id:
        print("FAIL: LYRA_NOTION_TASKS_DATABASE_ID not set")
        return 2

    client = NotionClient(token=settings.notion_token)

    print("=== 1) snapshot Projects/tasks row count (before) ===")
    before = client.query_database(settings.notion_tasks_database_id)
    before_ids = {r["id"] for r in before.get("results", [])}
    print(f"tasks rows before: {len(before_ids)}")

    print("\n=== 2) create Digests row (Type=research) ===")
    title = f"D1 live verify — {datetime.now(timezone.utc).isoformat()}"
    created = client.create_digest_page(
        database_id=settings.notion_digests_database_id,
        title=title,
        body="D1 acceptance check: this row must live in Digests, never Projects.",
        source_links=[],
        title_property=settings.notion_digest_title_property,
        digest_type="research",
    )
    digest_id = created["id"]
    digest_parent = created.get("parent", {}).get("database_id")
    print(f"created digest id={digest_id} parent_database_id={digest_parent}")

    if digest_parent != settings.notion_digests_database_id:
        print("FAIL: digest row parent is not the Digests database")
        return 1
    if digest_parent == settings.notion_tasks_database_id:
        print("FAIL: digest row parent equals the Projects/tasks database")
        return 1
    print("PASS: digest row parented to Digests DB, not Projects DB")

    print("\n=== 3) re-snapshot Projects/tasks row count (after) ===")
    after = client.query_database(settings.notion_tasks_database_id)
    after_ids = {r["id"] for r in after.get("results", [])}
    print(f"tasks rows after: {len(after_ids)}")

    new_task_rows = after_ids - before_ids
    if new_task_rows:
        print(f"FAIL: Projects/tasks database gained new row(s): {new_task_rows}")
        return 1
    print("PASS: Projects/tasks database row count unchanged")

    print("\n=== RESULT ===")
    print("D1 live e2e PASSED")
    print(f"  digest_id={digest_id}")
    print(f"  tasks_rows_before={len(before_ids)} tasks_rows_after={len(after_ids)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

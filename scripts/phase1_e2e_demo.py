"""Phase 1 exit demo (build plan Exit Criteria).

Flow: research ingest → corpus answer with citations → Notion digest →
propose + approve memory.

Usage:
  venv\\Scripts\\python scripts/phase1_e2e_demo.py
  venv\\Scripts\\python scripts/phase1_e2e_demo.py --skip-notion
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lyra.config import settings
from lyra.corpus_mcp import CorpusService
from lyra.db import apply_schema, connect
from lyra.embeddings import EmbeddingService
from lyra.ingest import IngestPipeline
from lyra.memory import MemoryService
from lyra.notion_sync import NotionClient

TOPIC = "quantum neural network ansatz"
SOURCE_URL = "https://arxiv.org/abs/1802.06002"
QUERY = "quantum neural network ansatz"


def _banner(step: str) -> None:
    print(f"\n=== {step} ===")


def main() -> int:
    parser = argparse.ArgumentParser(description="Lyra Phase 1 end-to-end demo")
    parser.add_argument(
        "--skip-notion",
        action="store_true",
        help="Skip live Notion digest (use when NOTION_TOKEN is unset)",
    )
    args = parser.parse_args()

    print("Lyra Phase 1 e2e demo")
    print(f"topic: {TOPIC}")
    print(f"db: {settings.db_host}:{settings.db_port}/{settings.db_name}")

    _banner("0) ensure schema")
    apply_schema()
    print("schema applied")

    embedder = EmbeddingService()
    ingest = IngestPipeline(embedding_service=embedder, connection_factory=connect)
    corpus = CorpusService(
        embedding_service=embedder,
        ingest_pipeline=ingest,
        connection_factory=connect,
    )
    memory = MemoryService(embedding_service=embedder, connection_factory=connect)

    _banner("1) research ingest")
    added = corpus.add_source(SOURCE_URL, source_type="url", title="arXiv: Continuous-variable quantum neural networks")
    print(f"source_id={added['source_id']} active={added['active_source_id']} deduped={added['was_deduped']}")

    _banner("2) corpus answer with citations")
    search = corpus.search_corpus(QUERY, limit=3)
    if not search["results"]:
        print("FAIL: no corpus hits")
        return 1
    for i, hit in enumerate(search["results"], start=1):
        cite = hit["citation"]
        print(
            f"[{i}] score={hit['score']:.3f} "
            f"title={cite.get('title')!r} url={cite.get('url')!r}"
        )
        print(f"    snippet: {hit['content'][:160].replace(chr(10), ' ')}...")

    _banner("3) Notion digest")
    digest_id = None
    if args.skip_notion:
        print("SKIPPED (--skip-notion)")
    else:
        if not settings.notion_token:
            print("FAIL: Notion token not set in .env")
            print("Add NOTION_TOKEN / NOTION_API_KEY, then re-run.")
            return 2
        if not settings.notion_digests_database_id:
            print("FAIL: LYRA_NOTION_DIGESTS_DATABASE_ID not set")
            print("Create Digests DB (not Projects):")
            print("  1) set LYRA_NOTION_PARENT_PAGE_ID to a normal Notion page UUID")
            print("  2) venv\\Scripts\\python scripts/notion_ensure_digests_db.py")
            print("  3) paste LYRA_NOTION_DIGESTS_DATABASE_ID into .env")
            return 2
        notion = NotionClient(token=settings.notion_token)
        body = (
            f"Phase 1 e2e digest for '{TOPIC}'.\n"
            f"Top hit: {search['results'][0]['content'][:280]}"
        )
        source_links = [
            c["citation"]["url"]
            for c in search["results"]
            if c.get("citation", {}).get("url")
        ] or [SOURCE_URL]
        created = notion.create_digest_page(
            database_id=settings.notion_digests_database_id,
            title=f"Lyra digest — {TOPIC} ({datetime.now(timezone.utc).date().isoformat()})",
            body=body,
            source_links=source_links,
            title_property=settings.notion_digest_title_property,
            digest_type="research",
            related_task_page_id=settings.notion_task_page_id,
        )
        digest_id = created["id"]
        print(f"created digest page id={digest_id}")
        readback = notion.read_sandbox_page(digest_id)
        title_prop = readback["page"].get("properties", {}).get(
            settings.notion_digest_title_property, {}
        )
        title_bits = title_prop.get("title") or []
        title_text = title_bits[0].get("plain_text") if title_bits else "(no title)"
        print(f"readback title={title_text!r} children={len(readback['children'])}")
        if settings.notion_task_page_id:
            try:
                notion.update_task_status(
                    settings.notion_task_page_id,
                    status="Done",
                    property_type=settings.notion_status_property_type,
                )
                print(f"updated task page {settings.notion_task_page_id} Status=Done")
            except Exception as exc:  # sandbox page may not have matching Status options
                print(f"task status update skipped/failed: {exc}")

    _banner("4) propose + approve memory")
    transcript = (
        f"We researched {TOPIC} and ingested {SOURCE_URL}. "
        "Corpus retrieval returned cited chunks. "
        "Next step is packaging findings for the D.Eng task roadmap."
    )
    created_memories = memory.writeback_session(transcript)
    if not created_memories:
        print("FAIL: write-back produced zero candidates")
        return 1
    print(f"candidates={len(created_memories)}")
    first = created_memories[0]
    print(f"pending memory_id={first['memory_id']} ledger={first['ledger']}")

    hidden = corpus.search_memories(QUERY, approved_only=True, limit=5)
    hidden_ids = {r["memory_id"] for r in hidden["results"]}
    if first["memory_id"] in hidden_ids:
        print("FAIL: unapproved memory already visible in search_memories")
        return 1
    print("unapproved memory correctly excluded from search")

    approved = memory.approve_memory(first["memory_id"])
    print(f"approved={approved}")
    visible = corpus.search_memories("D.Eng task roadmap", approved_only=True, limit=5)
    visible_ids = {r["memory_id"] for r in visible["results"]}
    if first["memory_id"] not in visible_ids:
        # Fallback query using candidate text
        visible = corpus.search_memories(first["content"][:80], approved_only=True, limit=5)
        visible_ids = {r["memory_id"] for r in visible["results"]}
    if first["memory_id"] not in visible_ids:
        print("FAIL: approved memory not returned by search_memories")
        return 1
    print("approved memory visible in search")

    _banner("RESULT")
    print("Phase 1 e2e demo PASSED")
    print(f"  ingest source_id={added['source_id']}")
    print(f"  corpus hits={len(search['results'])}")
    print(f"  notion_digest={digest_id or 'skipped'}")
    print(f"  memory_id={first['memory_id']} approved=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

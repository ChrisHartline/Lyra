from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


@dataclass(frozen=True)
class Settings:
    db_host: str = os.getenv("LYRA_DB_HOST", "127.0.0.1")
    db_port: int = int(os.getenv("LYRA_DB_PORT", "55432"))
    db_name: str = os.getenv("LYRA_DB_NAME", "lyra")
    db_user: str = os.getenv("LYRA_DB_USER", "lyra")
    db_password: str = os.getenv("LYRA_DB_PASSWORD", "lyra")
    notion_token: str | None = _first_env("NOTION_TOKEN", "NOTION_API_TOKEN", "NOTION_API_KEY")
    # Tasks board (Projects DB) — status updates only
    notion_tasks_database_id: str | None = _first_env(
        "LYRA_NOTION_TASKS_DATABASE_ID",
        "LYRA_NOTION_DATABASE_ID",
    )
    notion_task_page_id: str | None = os.getenv("LYRA_NOTION_PAGE_ID")
    notion_task_title_property: str = os.getenv("LYRA_NOTION_TITLE_PROPERTY", "Project name")
    notion_status_property_type: str = os.getenv("LYRA_NOTION_STATUS_PROPERTY_TYPE", "status")
    # Digests DB — research / daily / weekly digests only (never write digests into Projects)
    notion_digests_database_id: str | None = os.getenv("LYRA_NOTION_DIGESTS_DATABASE_ID")
    notion_digest_title_property: str = os.getenv("LYRA_NOTION_DIGEST_TITLE_PROPERTY", "Name")
    # Parent page used when ensuring/creating the Digests database
    notion_parent_page_id: str | None = os.getenv("LYRA_NOTION_PARENT_PAGE_ID")
    kg_memory_file_path: str = os.getenv(
        "LYRA_KG_MEMORY_FILE_PATH",
        str(
            Path("agents/lyra/state/knowledge_graph/memory.jsonl").resolve()
        ),
    )

    # Back-compat aliases used by older call sites
    @property
    def notion_database_id(self) -> str | None:
        return self.notion_tasks_database_id

    @property
    def notion_page_id(self) -> str | None:
        return self.notion_task_page_id

    @property
    def notion_title_property(self) -> str:
        return self.notion_task_title_property


settings = Settings()

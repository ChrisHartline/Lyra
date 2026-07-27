from __future__ import annotations

import os
from dataclasses import dataclass
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
    notion_token: str | None = _first_env("NOTION_TOKEN", "NOTION_API_TOKEN")
    notion_page_id: str | None = os.getenv("LYRA_NOTION_PAGE_ID")
    notion_database_id: str | None = os.getenv("LYRA_NOTION_DATABASE_ID")


settings = Settings()

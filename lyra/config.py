from __future__ import annotations

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    db_host: str = os.getenv("LYRA_DB_HOST", "localhost")
    db_port: int = int(os.getenv("LYRA_DB_PORT", "5432"))
    db_name: str = os.getenv("LYRA_DB_NAME", "lyra")
    db_user: str = os.getenv("LYRA_DB_USER", "lyra")
    db_password: str = os.getenv("LYRA_DB_PASSWORD", "lyra")
    notion_token: str | None = os.getenv("NOTION_API_TOKEN")


settings = Settings()

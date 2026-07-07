from __future__ import annotations

from dataclasses import dataclass
import requests

NOTION_VERSION = "2022-06-28"


@dataclass
class NotionClient:
    token: str

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    def get_page(self, page_id: str) -> dict:
        resp = requests.get(f"https://api.notion.com/v1/pages/{page_id}", headers=self._headers, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def get_block_children(self, block_id: str) -> dict:
        resp = requests.get(
            f"https://api.notion.com/v1/blocks/{block_id}/children?page_size=100",
            headers=self._headers,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def read_sandbox_page(self, page_id: str) -> dict:
        page = self.get_page(page_id)
        children = self.get_block_children(page_id)
        return {"page": page, "children": children.get("results", [])}

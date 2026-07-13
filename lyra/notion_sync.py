from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

NOTION_VERSION = "2022-06-28"


def _rich_text(content: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": {"content": content}, "plain_text": content}]


def _paragraph_block(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": _rich_text(text)},
    }


def _bulleted_link_block(url: str, label: str | None = None) -> dict[str, Any]:
    display = label or url
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [
                {
                    "type": "text",
                    "text": {"content": display, "link": {"url": url}},
                    "plain_text": display,
                    "href": url,
                }
            ]
        },
    }


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

    def update_task_status(self, page_id: str, status: str, property_name: str = "Status") -> dict:
        payload = {
            "properties": {
                property_name: {"select": {"name": status}},
            }
        }
        resp = requests.patch(
            f"https://api.notion.com/v1/pages/{page_id}",
            headers=self._headers,
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def create_digest_page(
        self,
        database_id: str,
        title: str,
        body: str,
        source_links: list[str],
        title_property: str = "Name",
    ) -> dict:
        children: list[dict[str, Any]] = [_paragraph_block(body)]
        if source_links:
            children.append(_paragraph_block("Sources:"))
            children.extend(_bulleted_link_block(link) for link in source_links)

        payload = {
            "parent": {"database_id": database_id},
            "properties": {
                title_property: {
                    "title": _rich_text(title),
                }
            },
            "children": children,
        }
        resp = requests.post(
            "https://api.notion.com/v1/pages",
            headers=self._headers,
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

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

    def query_database(self, database_id: str, page_size: int = 100) -> dict:
        resp = requests.post(
            f"https://api.notion.com/v1/databases/{database_id}/query",
            headers=self._headers,
            json={"page_size": page_size},
            timeout=30,
        )
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

    def update_task_status(
        self,
        page_id: str,
        status: str,
        property_name: str = "Status",
        property_type: str = "status",
    ) -> dict:
        if property_type == "status":
            prop_value: dict[str, Any] = {"status": {"name": status}}
        elif property_type == "select":
            prop_value = {"select": {"name": status}}
        else:
            raise ValueError(f"Unsupported property_type: {property_type}")
        payload = {"properties": {property_name: prop_value}}
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
        digest_type: str | None = None,
        related_task_page_id: str | None = None,
    ) -> dict:
        """Create a digest row in the Digests database (not the Projects/tasks board)."""
        children: list[dict[str, Any]] = [_paragraph_block(body)]
        if source_links:
            children.append(_paragraph_block("Sources:"))
            children.extend(_bulleted_link_block(link) for link in source_links)

        properties: dict[str, Any] = {
            title_property: {
                "title": _rich_text(title),
            }
        }
        if digest_type:
            properties["Type"] = {"select": {"name": digest_type}}
        if related_task_page_id:
            properties["Related task"] = {
                "rich_text": _rich_text(related_task_page_id),
            }

        payload = {
            "parent": {"database_id": database_id},
            "properties": properties,
            "children": children,
        }
        resp = requests.post(
            "https://api.notion.com/v1/pages",
            headers=self._headers,
            json=payload,
            timeout=30,
        )
        if not resp.ok:
            detail = ""
            try:
                detail = resp.json().get("message", "")
            except Exception:
                detail = resp.text[:300]
            raise requests.HTTPError(
                f"{resp.status_code} Client Error creating Notion page: {detail}",
                response=resp,
            )
        return resp.json()

    def ensure_digests_database(self, parent_page_id: str, title: str = "Lyra Digests") -> dict:
        """Create a Digests database under parent_page_id if needed (idempotent by title search)."""
        # Search for an existing DB with this title first.
        search = requests.post(
            "https://api.notion.com/v1/search",
            headers=self._headers,
            json={"query": title, "filter": {"value": "database", "property": "object"}},
            timeout=30,
        )
        search.raise_for_status()
        for result in search.json().get("results", []):
            titles = result.get("title") or []
            plain = "".join(t.get("plain_text", "") for t in titles)
            if plain.strip().lower() == title.strip().lower():
                return result

        payload = {
            "parent": {"type": "page_id", "page_id": parent_page_id},
            "title": [{"type": "text", "text": {"content": title}}],
            "properties": {
                "Name": {"title": {}},
                "Type": {
                    "select": {
                        "options": [
                            {"name": "research", "color": "blue"},
                            {"name": "daily", "color": "green"},
                            {"name": "weekly", "color": "purple"},
                            {"name": "personal", "color": "yellow"},
                            {"name": "professional", "color": "orange"},
                        ]
                    }
                },
                "Date": {"date": {}},
                "Related task": {"rich_text": {}},
                "Sources": {"url": {}},
            },
        }
        resp = requests.post(
            "https://api.notion.com/v1/databases",
            headers=self._headers,
            json=payload,
            timeout=30,
        )
        if not resp.ok:
            detail = ""
            try:
                detail = resp.json().get("message", "")
            except Exception:
                detail = resp.text[:300]
            raise requests.HTTPError(
                f"{resp.status_code} Client Error creating Digests database: {detail}",
                response=resp,
            )
        return resp.json()

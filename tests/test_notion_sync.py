from __future__ import annotations

import responses
from lyra.notion_sync import NotionClient


@responses.activate
def test_b1_read_sandbox_page_reflects_updates():
    client = NotionClient(token="test-token")
    page_id = "sandbox-page-id"

    responses.add(
        responses.GET,
        f"https://api.notion.com/v1/pages/{page_id}",
        json={"id": page_id, "properties": {"Status": {"select": {"name": "Draft"}}}},
        status=200,
    )
    responses.add(
        responses.GET,
        f"https://api.notion.com/v1/blocks/{page_id}/children?page_size=100",
        json={"results": [{"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "v1"}]}}]},
        status=200,
    )

    first = client.read_sandbox_page(page_id)
    assert first["page"]["properties"]["Status"]["select"]["name"] == "Draft"

    responses.add(
        responses.GET,
        f"https://api.notion.com/v1/pages/{page_id}",
        json={"id": page_id, "properties": {"Status": {"select": {"name": "Updated"}}}},
        status=200,
    )
    responses.add(
        responses.GET,
        f"https://api.notion.com/v1/blocks/{page_id}/children?page_size=100",
        json={"results": [{"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "v2"}]}}]},
        status=200,
    )

    second = client.read_sandbox_page(page_id)
    assert second["page"]["properties"]["Status"]["select"]["name"] == "Updated"
    assert second["children"][0]["paragraph"]["rich_text"][0]["plain_text"] == "v2"

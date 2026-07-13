from __future__ import annotations

import json

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


@responses.activate
def test_b2_create_digest_and_update_task_verified_by_readback():
    client = NotionClient(token="test-token")
    database_id = "sandbox-database-id"
    task_page_id = "sandbox-task-page-id"
    digest_page_id = "created-digest-page-id"
    title = "QNN Research Digest"
    body = "Summarized findings on QNN ansatz stability."
    source_links = ["https://example.com/qnn", "https://example.com/ansatz"]

    def _create_digest_callback(request):
        payload = json.loads(request.body)
        assert payload["parent"]["database_id"] == database_id
        assert payload["properties"]["Name"]["title"][0]["plain_text"] == title
        children = payload["children"]
        assert children[0]["paragraph"]["rich_text"][0]["plain_text"] == body
        link_texts = [
            block["bulleted_list_item"]["rich_text"][0]["href"]
            for block in children
            if block["type"] == "bulleted_list_item"
        ]
        assert link_texts == source_links
        return (
            200,
            {},
            json.dumps(
                {
                    "id": digest_page_id,
                    "parent": {"database_id": database_id},
                    "properties": {
                        "Name": {"title": [{"plain_text": title}]},
                    },
                }
            ),
        )

    responses.add_callback(
        responses.POST,
        "https://api.notion.com/v1/pages",
        callback=_create_digest_callback,
        content_type="application/json",
    )

    created = client.create_digest_page(
        database_id=database_id,
        title=title,
        body=body,
        source_links=source_links,
    )
    assert created["id"] == digest_page_id

    # Read-back via B1 path confirms title, body, and source links.
    responses.add(
        responses.GET,
        f"https://api.notion.com/v1/pages/{digest_page_id}",
        json={
            "id": digest_page_id,
            "parent": {"database_id": database_id},
            "properties": {"Name": {"title": [{"plain_text": title}]}},
        },
        status=200,
    )
    responses.add(
        responses.GET,
        f"https://api.notion.com/v1/blocks/{digest_page_id}/children?page_size=100",
        json={
            "results": [
                {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": body}]}},
                {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Sources:"}]}},
                {
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {
                        "rich_text": [{"plain_text": source_links[0], "href": source_links[0]}]
                    },
                },
                {
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {
                        "rich_text": [{"plain_text": source_links[1], "href": source_links[1]}]
                    },
                },
            ]
        },
        status=200,
    )

    digest_read = client.read_sandbox_page(digest_page_id)
    assert digest_read["page"]["properties"]["Name"]["title"][0]["plain_text"] == title
    assert digest_read["children"][0]["paragraph"]["rich_text"][0]["plain_text"] == body
    read_links = [
        c["bulleted_list_item"]["rich_text"][0]["href"]
        for c in digest_read["children"]
        if c["type"] == "bulleted_list_item"
    ]
    assert read_links == source_links

    def _update_task_callback(request):
        payload = json.loads(request.body)
        assert payload["properties"]["Status"]["select"]["name"] == "Done"
        return (
            200,
            {},
            json.dumps(
                {
                    "id": task_page_id,
                    "properties": {"Status": {"select": {"name": "Done"}}},
                }
            ),
        )

    responses.add_callback(
        responses.PATCH,
        f"https://api.notion.com/v1/pages/{task_page_id}",
        callback=_update_task_callback,
        content_type="application/json",
    )

    updated = client.update_task_status(task_page_id, status="Done")
    assert updated["properties"]["Status"]["select"]["name"] == "Done"

    responses.add(
        responses.GET,
        f"https://api.notion.com/v1/pages/{task_page_id}",
        json={"id": task_page_id, "properties": {"Status": {"select": {"name": "Done"}}}},
        status=200,
    )
    responses.add(
        responses.GET,
        f"https://api.notion.com/v1/blocks/{task_page_id}/children?page_size=100",
        json={"results": []},
        status=200,
    )

    task_read = client.read_sandbox_page(task_page_id)
    assert task_read["page"]["properties"]["Status"]["select"]["name"] == "Done"

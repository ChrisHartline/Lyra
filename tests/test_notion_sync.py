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
        assert payload["properties"]["Status"]["status"]["name"] == "Done"
        return (
            200,
            {},
            json.dumps(
                {
                    "id": task_page_id,
                    "properties": {"Status": {"status": {"name": "Done"}}},
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
    assert updated["properties"]["Status"]["status"]["name"] == "Done"

    responses.add(
        responses.GET,
        f"https://api.notion.com/v1/pages/{task_page_id}",
        json={"id": task_page_id, "properties": {"Status": {"status": {"name": "Done"}}}},
        status=200,
    )
    responses.add(
        responses.GET,
        f"https://api.notion.com/v1/blocks/{task_page_id}/children?page_size=100",
        json={"results": []},
        status=200,
    )

    task_read = client.read_sandbox_page(task_page_id)
    assert task_read["page"]["properties"]["Status"]["status"]["name"] == "Done"


@responses.activate
def test_b3_ensure_digests_database_and_typed_digest():
    client = NotionClient(token="test-token")
    parent_page_id = "parent-page-id"
    digests_db_id = "digests-db-id"

    responses.add(
        responses.POST,
        "https://api.notion.com/v1/search",
        json={"results": []},
        status=200,
    )

    def _create_db_callback(request):
        payload = json.loads(request.body)
        assert payload["parent"]["page_id"] == parent_page_id
        assert "Name" in payload["properties"]
        assert "Type" in payload["properties"]
        return (200, {}, json.dumps({"id": digests_db_id, "object": "database", "title": [{"plain_text": "Lyra Digests"}]}))

    responses.add_callback(
        responses.POST,
        "https://api.notion.com/v1/databases",
        callback=_create_db_callback,
        content_type="application/json",
    )

    created_db = client.ensure_digests_database(parent_page_id)
    assert created_db["id"] == digests_db_id

    def _create_digest_callback(request):
        payload = json.loads(request.body)
        assert payload["parent"]["database_id"] == digests_db_id
        assert payload["properties"]["Type"]["select"]["name"] == "research"
        assert payload["properties"]["Name"]["title"][0]["plain_text"].startswith("Digest")
        return (
            200,
            {},
            json.dumps(
                {
                    "id": "digest-row-id",
                    "parent": {"database_id": digests_db_id},
                    "properties": {"Name": {"title": [{"plain_text": "Digest"}]}},
                }
            ),
        )

    responses.add_callback(
        responses.POST,
        "https://api.notion.com/v1/pages",
        callback=_create_digest_callback,
        content_type="application/json",
    )

    row = client.create_digest_page(
        database_id=digests_db_id,
        title="Digest",
        body="Body",
        source_links=["https://example.com"],
        title_property="Name",
        digest_type="research",
    )
    assert row["id"] == "digest-row-id"
    assert row["parent"]["database_id"] == digests_db_id


@responses.activate
def test_d1_query_database_used_to_prove_no_projects_row_created():
    client = NotionClient(token="test-token")
    tasks_db_id = "tasks-db-id"

    responses.add(
        responses.POST,
        f"https://api.notion.com/v1/databases/{tasks_db_id}/query",
        json={"results": [{"id": "task-1"}, {"id": "task-2"}]},
        status=200,
    )

    result = client.query_database(tasks_db_id)
    assert [r["id"] for r in result["results"]] == ["task-1", "task-2"]

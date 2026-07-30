from __future__ import annotations

from datetime import date
from typing import Any

from lyra.digests import DigestService


class RecordingPublisher:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

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
        payload = {
            "database_id": database_id,
            "title": title,
            "body": body,
            "source_links": source_links,
            "title_property": title_property,
            "digest_type": digest_type,
            "related_task_page_id": related_task_page_id,
        }
        self.calls.append(payload)
        return {
            "id": f"digest-{len(self.calls)}",
            "parent": {"database_id": database_id},
            "properties": {"Name": {"title": [{"plain_text": title}]}},
        }


def _service(publisher: RecordingPublisher | None = None) -> tuple[DigestService, RecordingPublisher]:
    pub = publisher or RecordingPublisher()
    service = DigestService(
        publisher=pub,
        digests_database_id="digests-db-id",
        title_property="Name",
    )
    return service, pub


def test_d2_daily_and_weekly_digests_have_type_and_dated_sections():
    service, publisher = _service()
    as_of = date(2026, 7, 30)

    daily = service.publish(
        "daily",
        as_of=as_of,
        personal_items=["Walked after dinner"],
        professional_items=["Advanced Lyra digest jobs"],
        gather=False,
    )
    weekly = service.publish(
        "weekly",
        as_of=as_of,
        personal_items=["Kept evening wind-down"],
        professional_items=["Closed D1 and started D2"],
        gather=False,
    )

    assert daily["digest_type"] == "daily"
    assert weekly["digest_type"] == "weekly"
    assert len(publisher.calls) == 2
    assert publisher.calls[0]["digest_type"] == "daily"
    assert publisher.calls[1]["digest_type"] == "weekly"

    for call in publisher.calls:
        body = call["body"]
        assert "2026-07-30" in body
        assert "## Personal" in body
        assert "## Professional" in body
        assert "Window:" in body

    assert "2026-07-24 → 2026-07-30" in weekly["body"]


def test_d2_never_persist_material_is_excluded_from_digest_body():
    service, publisher = _service()
    as_of = date(2026, 7, 30)

    result = service.publish(
        "daily",
        as_of=as_of,
        personal_items=[
            "API key is xai-123456789SECRET and password is hunter2",
            "Prefers quiet mornings for deep work",
        ],
        professional_items=[
            "token=super-secret-value",
            "Shipped digest generator",
        ],
        gather=False,
    )

    body = result["body"]
    assert "xai-123456789SECRET" not in body
    assert "password is hunter2" not in body
    assert "token=super-secret-value" not in body
    assert "Prefers quiet mornings for deep work" in body
    assert "Shipped digest generator" in body
    assert publisher.calls[0]["digest_type"] == "daily"

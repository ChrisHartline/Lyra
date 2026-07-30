from __future__ import annotations

from datetime import date
from typing import Any

from lyra.briefings import BriefingService


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
            "digest_type": digest_type,
        }
        self.calls.append(payload)
        return {"id": f"briefing-{len(self.calls)}", "parent": {"database_id": database_id}}


def test_d5_briefing_cites_planes_and_excludes_story_campaign():
    service = BriefingService(digests_database_id="digests-db")
    result = service.assemble(
        "morning",
        as_of=date(2026, 7, 30),
        digest_items=["Daily digest closed D2"],
        observation_items=["Christopher: Prefers gated delivery"],
        memory_items=[
            "Session note: Advanced the Lyra briefing assembly",
            "Story canon update: Lyra repaired the ship phase regulator",
            "Campaign log: rolled initiative against an orc patrol",
        ],
        gather=False,
        for_notion=False,
    )

    planes = {bullet["plane"] for bullet in result["bullets"]}
    assert planes == {"digest", "observation", "memory"}
    assert "[digest]" in result["body"]
    assert "[observation]" in result["body"]
    assert "[memory]" in result["body"]
    assert "phase regulator" not in result["body"]
    assert "orc patrol" not in result["body"]
    assert "Advanced the Lyra briefing assembly" in result["body"]


def test_d5_notion_publish_filters_intimate_personal_content():
    publisher = RecordingPublisher()
    service = BriefingService(
        digests_database_id="digests-db",
        publisher=publisher,
    )
    published = service.publish_to_notion(
        "morning",
        as_of=date(2026, 7, 30),
        digest_items=["Shipped D2 digests"],
        observation_items=["Christopher: Discussed PTSD support boundary"],
        memory_items=["API key is xai-123456789SECRET"],
        gather=False,
    )

    assert "Shipped D2 digests" in published["body"]
    assert "PTSD" not in published["body"]
    assert "xai-123456789SECRET" not in published["body"]
    assert published["digest_id"].startswith("briefing-")
    assert publisher.calls[-1]["digest_type"] == "daily"

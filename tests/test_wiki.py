from __future__ import annotations

import asyncio
import json
from pathlib import Path
import shutil
import uuid

import pytest

from lyra.knowledge_routing import ROUTES, route_knowledge, routing_prompt
from lyra.runtime_tools import build_conversation_registry
from lyra.wiki import WikiPageNotFound, WikiService, validate_wiki_catalog


ROOT = Path(__file__).resolve().parents[1]


def _case(name: str) -> Path:
    path = ROOT / "data" / "test_tmp" / f"wiki_{name}_{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True)
    return path


def test_catalog_validates_and_exposes_only_lyra_allowlist():
    assert validate_wiki_catalog(ROOT) == []
    wiki = WikiService(ROOT)

    assert len(wiki.page_ids) == 9
    assert "backstory.vossari_culture" in wiki.page_ids
    assert "locations.stable_places" in wiki.page_ids
    assert all(not page.startswith("personality.") for page in wiki.page_ids)


def test_lexical_search_is_bucketed_deterministic_and_provenance_aware():
    wiki = WikiService(ROOT)

    first = wiki.search("Hollow Ribbon", bucket="place")
    second = wiki.search("Hollow Ribbon", bucket="place")

    assert first == second
    assert first["retrieval"] == "lexical"
    assert first["results"][0]["page_id"] == "locations.stable_places"
    assert first["results"][0]["bucket"] == "place"
    assert first["results"][0]["provenance"]
    assert first["results"][0]["epistemic_status"] == "reference_not_lived_memory"
    assert "remembered interaction" in first["results"][0]["usage_warning"]
    assert wiki.search("Hollow Ribbon", bucket="expertise")["results"] == []


def test_read_uses_page_ids_and_missing_or_cross_bucket_paths_fail_closed():
    wiki = WikiService(ROOT)
    page = wiki.read("backstory.vossari_culture")

    assert "orbital habitats" in page["content"]
    assert page["agent_id"] == "lyra"
    assert page["authority"] == "standing_reference"
    assert page["truncated"] is False

    for forbidden in (
        "personality/system_prompt.md",
        "../personality/system_prompt.md",
        "other_agent.private_page",
    ):
        with pytest.raises(WikiPageNotFound):
            wiki.read(forbidden)


def test_catalog_rejects_prompt_state_source_material_and_chat_ingest():
    case = _case("blocked")
    try:
        catalog_dir = case / "agents" / "lyra" / "wiki"
        catalog_dir.mkdir(parents=True)
        (case / "personality").mkdir()
        prompt = case / "personality" / "system_prompt.md"
        prompt.write_text("secret prompt", encoding="utf-8")
        catalog = {
            "version": "1.0",
            "agent_id": "lyra",
            "retrieval": "lexical",
            "automatic_chat_ingest": True,
            "pages": [
                {
                    "page_id": "leak.prompt",
                    "title": "Prompt",
                    "path": "personality/system_prompt.md",
                    "bucket": "lore",
                    "tags": [],
                    "provenance": ["chat.session.1"],
                    "sha256": "wrong",
                },
                {
                    "page_id": "leak.source",
                    "title": "Source",
                    "path": "agents/lyra/references/source_material/raw.md",
                    "bucket": "lore",
                    "tags": [],
                    "provenance": ["source.raw"],
                    "sha256": "wrong",
                },
            ],
        }
        (catalog_dir / "catalog.json").write_text(
            json.dumps(catalog), encoding="utf-8"
        )

        errors = validate_wiki_catalog(case)

        assert any("automatic_chat_ingest must be false" in error for error in errors)
        assert any("outside agent wiki allowlist" in error for error in errors)
        assert any("source material cannot be exposed" in error for error in errors)
        assert any("chat/session logs cannot be wiki provenance" in error for error in errors)
        assert validate_wiki_catalog(case, "../other") == [
            "invalid agent_id: '../other'"
        ]
    finally:
        shutil.rmtree(case, ignore_errors=True)


def test_prompt_phrases_and_unregistered_pages_do_not_leak_through_search():
    wiki = WikiService(ROOT)
    result = wiki.search("transactional nickname flirting")

    assert result["results"] == []
    assert "Christopher's girlfriend" not in json.dumps(result)
    assert "reference, not evidence of a lived interaction" in routing_prompt()


def test_every_information_class_has_one_explicit_authority():
    assert set(ROUTES) == {
        "persona_contract",
        "standing_reference",
        "research_source",
        "approved_observation",
        "episodic_memory",
        "ship_definition_or_status",
        "story_continuity",
        "campaign_state",
    }
    assert route_knowledge("standing_reference")["read_tools"] == (
        "wiki_search",
        "wiki_read",
    )
    assert route_knowledge("campaign_state")["plane"] == "campaign_state"
    assert route_knowledge("ship_definition_or_status")["authority"].startswith("ship/")
    with pytest.raises(ValueError):
        route_knowledge("guess")


def test_conversation_registry_exposes_read_only_wiki_and_route_contracts():
    class Router:
        def __init__(self):
            self.calls = []

        def call_tool(self, name, arguments):
            self.calls.append((name, arguments))
            return {"name": name, "arguments": arguments}

    corpus = Router()
    memory = Router()
    wiki = Router()
    registry = build_conversation_registry(
        corpus_router=corpus, memory_router=memory, wiki_router=wiki
    )

    search = asyncio.run(registry.invoke("wiki_search", {"query": "Vossari"}))
    read = asyncio.run(registry.invoke("wiki_read", {"page_id": "backstory.origin"}))
    route = asyncio.run(
        registry.invoke("knowledge_route", {"information_type": "research_source"})
    )

    assert search["name"] == "wiki_search"
    assert read["name"] == "wiki_read"
    assert route["plane"] == "corpus"
    assert {"wiki_search", "wiki_read", "knowledge_route"} <= set(registry.names)
    assert {"wiki_search", "wiki_read", "knowledge_route"} <= set(
        registry.read_only().names
    )

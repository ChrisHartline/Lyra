"""Authoritative knowledge-plane routing for the conversation runtime."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class KnowledgeRoute:
    information_type: str
    plane: str
    authority: str
    read_tools: tuple[str, ...]
    durable_write: str
    epistemic_status: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


ROUTES = {
    route.information_type: route
    for route in (
        KnowledgeRoute(
            "persona_contract",
            "tier_0",
            "personality/",
            (),
            "Christopher hand-edit only",
            "identity_and_interaction_contract",
        ),
        KnowledgeRoute(
            "standing_reference",
            "reference_wiki",
            "allowlisted canonical Markdown",
            ("wiki_search", "wiki_read"),
            "Git-reviewed file edit only; never automatic chat ingestion",
            "reference_not_lived_memory",
        ),
        KnowledgeRoute(
            "research_source",
            "corpus",
            "PostgreSQL sources/chunks with citations",
            ("search_corpus",),
            "explicit source ingestion",
            "external_or_user_supplied_source",
        ),
        KnowledgeRoute(
            "approved_observation",
            "knowledge_graph",
            "approved local KG observations",
            ("search_nodes", "open_nodes", "read_graph"),
            "propose_observation then human approval",
            "approved_observation_not_episode",
        ),
        KnowledgeRoute(
            "episodic_memory",
            "semantic_memory",
            "approved PostgreSQL memory ledger",
            ("search_memories",),
            "proposal or explicit-memory approval flow",
            "approved_recollection",
        ),
        KnowledgeRoute(
            "ship_definition_or_status",
            "ship_state",
            "ship/ and ship/current_status.json",
            (),
            "ship continuity approval flow",
            "canonical_ship_fact_or_live_status",
        ),
        KnowledgeRoute(
            "story_continuity",
            "story_state",
            "state/story/",
            (),
            "approved story-memory regeneration",
            "canonical_story_state",
        ),
        KnowledgeRoute(
            "campaign_state",
            "campaign_state",
            "named VTT/campaign repository",
            (),
            "campaign-specific workflow only",
            "campaign_only_not_biography",
        ),
    )
}


def route_knowledge(information_type: str) -> dict[str, object]:
    """Return the one authoritative destination for a classified information type."""
    try:
        return ROUTES[information_type].as_dict()
    except KeyError as exc:
        allowed = ", ".join(sorted(ROUTES))
        raise ValueError(
            f"Unknown information_type {information_type!r}; choose one of: {allowed}"
        ) from exc


def routing_prompt() -> str:
    """Operational retrieval policy appended to runtime context, outside Tier 0."""
    return (
        "# Knowledge retrieval policy\n\n"
        "Use knowledge_route when the authoritative plane is unclear. Use wiki_search "
        "and wiki_read only for standing reference material. Wiki results are authored "
        "reference, not evidence of a lived interaction, personal recollection, or "
        "anecdote; never claim Lyra remembers a wiki passage. Keep Tier 0, corpus, "
        "knowledge-graph observations, episodic memory, ship state, story state, and "
        "campaign state in their declared buckets. Do not move or persist retrieved "
        "material merely because it was retrieved."
    )

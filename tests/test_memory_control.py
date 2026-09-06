from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from lyra.corpus_mcp import CorpusService
from lyra.knowledge_graph import ObservationService
from lyra.memory_control import MemoryControlService
from tests.db_support import connect_test_db


def _conn():
    return connect_test_db()


class FakeEmbedder:
    def embed_texts(self, texts):
        vectors = []
        for index, _text in enumerate(texts):
            vector = np.zeros(384, dtype=np.float32)
            vector[index % 384] = 1.0
            vectors.append(vector)
        return np.array(vectors)


class FakeIngest:
    pass


class RecordingGraphWriter:
    def __init__(self):
        self.added = []
        self.deleted = []

    def add_observation(self, entity_name, entity_type, content):
        self.added.append((entity_name, entity_type, content))
        return {"ok": True}

    def delete_observation(self, entity_name, content):
        self.deleted.append((entity_name, content))
        return {"ok": True}


def _reset():
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(Path("db/schema.sql").read_text(encoding="utf-8"))
            cur.execute(
                "TRUNCATE memory_review_audit, memories RESTART IDENTITY CASCADE"
            )
        conn.commit()


def _services():
    embedder = FakeEmbedder()
    writer = RecordingGraphWriter()
    control = MemoryControlService(embedder, writer, _conn)
    corpus = CorpusService(embedder, FakeIngest(), _conn)
    observations = ObservationService(embedder, writer, _conn)
    return control, corpus, observations, writer


def test_control_center_lists_provenance_and_approves_both_planes(ensure_db):
    _reset()
    control, corpus, observations, writer = _services()
    semantic = corpus.propose_memory(
        "Christopher is assembling a curated list of meaningful places.",
        metadata={
            "ledger": "biography",
            "source_type": "manual_note",
            "source_id": "places.md",
            "proposal_reason": "Stable personal context",
            "sensitivity_flags": ["personal"],
        },
    )
    graph = observations.propose_observations(
        "Christopher prefers explicit memory approval before durable storage.",
        entity_name="Christopher",
        entity_type="person",
        source_type="session",
    )[0]

    pending = control.list_proposals()

    assert {item["destination_plane"] for item in pending} == {
        "semantic_memory",
        "knowledge_graph",
    }
    semantic_view = next(
        item for item in pending if item["proposal_id"] == semantic["memory_id"]
    )
    assert semantic_view["provenance"]["source_id"] == "places.md"
    assert semantic_view["proposal_reason"] == "Stable personal context"
    assert semantic_view["sensitivity_flags"] == ["personal"]

    control.approve(semantic["memory_id"])
    control.approve(graph["observation_id"])

    assert len(control.list_proposals(status="approved")) == 2
    assert writer.added == [
        (
            "Christopher",
            "person",
            "Christopher prefers explicit memory approval before durable storage",
        )
    ]
    assert [item["action"] for item in control.list_audit()] == [
        "approved",
        "approved",
    ]


def test_correction_revalidates_dlp_and_rejection_leaves_no_fact(ensure_db):
    _reset()
    control, corpus, _observations, _writer = _services()
    proposal = corpus.propose_memory(
        "Christopher enjoys returning to quiet lakeside places.",
        metadata={"ledger": "biography"},
    )
    proposal_id = proposal["memory_id"]

    with pytest.raises(ValueError, match="never-persist"):
        control.correct(proposal_id, "My password is hunter2")
    with pytest.raises(ValueError, match="never-persist"):
        control.reject(proposal_id, reason="My password is hunter2")

    corrected = control.correct(
        proposal_id,
        "Christopher enjoys returning to quiet forest cabins.",
        reason="More precise",
    )
    assert corrected["content"].endswith("forest cabins.")

    control.reject(proposal_id, reason="Do not retain this preference")

    assert control.list_proposals() == []
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM memories WHERE id = %s", (proposal_id,))
            assert cur.fetchone()[0] == 0
    audit = control.list_audit()
    assert [item["action"] for item in audit] == ["rejected", "corrected"]
    assert all("forest" not in str(item) for item in audit)


def test_approval_rechecks_legacy_candidate_against_never_persist(ensure_db):
    _reset()
    control, _corpus, _observations, _writer = _services()
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO memories (
                    content, memory_type, metadata, approved, review_status
                )
                VALUES (
                    'password=hunter2', 'fact',
                    '{"ledger":"biography"}'::jsonb, false, 'pending'
                )
                RETURNING id
                """
            )
            proposal_id = int(cur.fetchone()[0])
        conn.commit()

    with pytest.raises(ValueError, match="never-persist"):
        control.approve(proposal_id)

    assert control.list_proposals()[0]["proposal_id"] == proposal_id
    assert control.list_audit() == []


def test_forget_requires_confirmation_and_removes_semantic_and_graph_retrieval(
    ensure_db,
):
    _reset()
    control, corpus, observations, writer = _services()
    semantic_id = corpus.propose_memory(
        "Christopher likes carefully governed memory systems.",
        metadata={"ledger": "biography"},
    )["memory_id"]
    graph_id = observations.propose_observations(
        "Christopher values reversible and auditable system changes.",
        entity_name="Christopher",
        entity_type="person",
    )[0]["observation_id"]
    control.approve(semantic_id)
    control.approve(graph_id)

    with pytest.raises(ValueError, match="confirmation"):
        control.forget(semantic_id, confirmed=False)

    control.forget(semantic_id, confirmed=True)
    control.forget(graph_id, confirmed=True, reason="User requested removal")

    assert control.list_proposals(status="approved") == []
    assert writer.deleted == [
        (
            "Christopher",
            "Christopher values reversible and auditable system changes",
        )
    ]
    forgotten = [
        item for item in control.list_audit() if item["action"] == "forgotten"
    ]
    assert len(forgotten) == 2
    assert all(len(item["content_sha256"]) == 64 for item in forgotten)

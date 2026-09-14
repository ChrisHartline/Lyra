from __future__ import annotations

from pathlib import Path

import numpy as np

from lyra.corpus_mcp import CorpusService
from lyra.briefings import BriefingService
from lyra.digests import DigestService
from lyra.memory_control import MemoryControlService
from lyra.natural_memory import MemoryPolicyService, NaturalMemoryService
from lyra.sessions import SessionService
from tests.db_support import connect_test_db


def _conn():
    return connect_test_db()


class FakeEmbedder:
    def embed_texts(self, texts):
        vectors = []
        for _text in texts:
            vector = np.zeros(384, dtype=np.float32)
            vector[0] = 1.0
            vectors.append(vector)
        return np.array(vectors)


class FakeIngest:
    pass


class FakeGraph:
    def add_observation(self, *args):
        raise AssertionError("natural memory must not write the KG")

    def delete_observation(self, *args):
        raise AssertionError("natural memory must not mutate the KG")


def _services():
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(Path("db/schema.sql").read_text(encoding="utf-8"))
        cur.execute("TRUNCATE memory_control_intents, memory_review_audit, memories, chat_sessions RESTART IDENTITY CASCADE")
        cur.execute("""UPDATE memory_policy SET private_shared_mode='auto',
                       professional_mode='review',story_mode='auto',campaign_mode='auto'""")
        conn.commit()
    embedder = FakeEmbedder()
    corpus = CorpusService(embedder, FakeIngest(), _conn)
    control = MemoryControlService(embedder, FakeGraph(), _conn)
    natural = NaturalMemoryService(corpus, control, _conn)
    sessions = SessionService(_conn)
    session = sessions.create_session("Natural memory")
    return natural, control, sessions, session["session_id"]


def _observe(natural, sessions, session_id, text, ledger="biography"):
    message = sessions.append_message(session_id, "user", text)
    return natural.observe_message(
        session_id=session_id, message_id=message["message_id"], text=text,
        ledger=ledger, channel="telegram",
    )


def test_segmented_defaults_and_explicit_approval(ensure_db):
    natural, control, sessions, session_id = _services()

    private = _observe(natural, sessions, session_id, "I prefer quiet mornings")
    professional = _observe(natural, sessions, session_id, "I prefer written project plans")
    transient = _observe(natural, sessions, session_id, "I'm stressed today")
    explicit = _observe(natural, sessions, session_id, "Remember that I use Docker for work")

    assert private.action == "approved"
    assert professional.action == "pending"
    assert transient.action == "none"
    assert explicit.action == "approved"
    recent = control.list_recent_natural()
    assert {item["approval_mode"] for item in recent} == {"auto", "explicit"}
    assert all(item["provenance"]["channel"] == "telegram" for item in recent)
    assert control.list_proposals()[0]["trust_lane"] == "professional"
    actors = {item["actor"] for item in control.list_audit()}
    assert actors == {"memory_policy", "explicit_user"}
    digest_memories = DigestService(None, "unused", connection_factory=_conn)._gather_memories()
    briefing_memories = BriefingService("unused", connection_factory=_conn)._gather_biography_memories()
    assert all("quiet mornings" not in item for item in digest_memories + briefing_memories)
    assert any("Docker for work" in item for item in digest_memories)


def test_never_persist_exclusion_correction_and_confirmed_forget(ensure_db):
    natural, control, sessions, session_id = _services()
    blocked = _observe(natural, sessions, session_id, "Remember that my password is hunter2")
    excluded = _observe(natural, sessions, session_id, "Don't remember this")
    created = _observe(natural, sessions, session_id, "I like forest cabins")

    assert blocked.action == "blocked"
    assert excluded.action == "excluded"
    assert len(control.list_proposals(status="approved")) == 1

    corrected = _observe(natural, sessions, session_id, "Correct that to I love forest cabins")
    assert corrected.action == "corrected"
    assert control.list_proposals(status="approved")[0]["content"].endswith("I love forest cabins")

    offered = _observe(natural, sessions, session_id, "Forget about forest cabins")
    assert offered.action == "confirm_forget"
    confirmed = _observe(natural, sessions, session_id, "Yes, forget it")
    assert confirmed.action == "forgotten"
    assert control.list_proposals(status="approved") == []


def test_policy_modes_and_bucket_isolation(ensure_db):
    natural, control, sessions, session_id = _services()
    policy = MemoryPolicyService(_conn)
    policy.set_policy(private_shared="off", professional="review", story="auto", campaign="auto")

    assert _observe(natural, sessions, session_id, "I like tea").action == "off"
    story = _observe(natural, sessions, session_id, "Remember that the ship has a blue observation deck", "story")
    assert story.action == "approved"
    stored = control.list_proposals(status="approved")[0]
    assert stored["ledger"] == "story"
    assert stored["trust_lane"] == "story"

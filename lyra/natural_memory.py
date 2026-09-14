"""Deterministic, segmented conversational memory policy (W6.1a)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
import uuid
from typing import Any, Callable

import psycopg

from .corpus_mcp import CorpusService
from .db import connect
from .memory import validate_persistable_text
from .memory_control import MemoryControlService


MODES = frozenset({"auto", "review", "off"})
PROFESSIONAL = re.compile(
    r"\b(project|work|research|paper|client|employer|job|career|code|docker|"
    r"database|github|notion|thesis|dissertation|class|student|university|"
    r"deadline|model)\b",
    re.I,
)
STABLE = re.compile(
    r"^(?:i (?:like|love|prefer|enjoy|dislike|hate|value|appreciate|trust|"
    r"usually|often|always|tend to|live in|grew up|am from)\b|my favorite\b|"
    r"this means a lot to me\b|i feel (?:close|safe|connected) when\b)",
    re.I,
)
TRANSIENT = re.compile(
    r"^i(?:'m| am) (?:overwhelmed|stressed|frustrated|anxious|sad|happy|angry|tired)\b",
    re.I,
)


@dataclass(frozen=True)
class NaturalMemoryObservation:
    action: str = "none"
    instruction: str | None = None
    memory_id: int | None = None


@dataclass
class MemoryPolicyService:
    connection_factory: Callable[[], psycopg.Connection] = connect

    def get_policy(self) -> dict[str, str]:
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT private_shared_mode, professional_mode, story_mode,
                          campaign_mode FROM memory_policy WHERE singleton = true"""
            )
            row = cur.fetchone()
        if not row:
            raise ValueError("Memory policy is not initialized")
        return dict(zip(("private_shared", "professional", "story", "campaign"), row))

    def set_policy(self, **modes: str) -> dict[str, str]:
        current = self.get_policy()
        unknown = set(modes) - set(current)
        if unknown or any(mode not in MODES for mode in modes.values()):
            raise ValueError("Memory policy lanes accept only auto, review, or off")
        current.update(modes)
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE memory_policy SET private_shared_mode=%s,
                          professional_mode=%s, story_mode=%s, campaign_mode=%s,
                          updated_at=now() WHERE singleton=true""",
                tuple(current[key] for key in ("private_shared", "professional", "story", "campaign")),
            )
            conn.commit()
        return current


@dataclass
class NaturalMemoryService:
    corpus: CorpusService
    control: MemoryControlService
    connection_factory: Callable[[], psycopg.Connection] = connect
    intent_ttl_minutes: int = 15

    def observe_message(
        self, *, session_id: str, message_id: int, text: str,
        ledger: str = "biography", channel: str = "web",
    ) -> NaturalMemoryObservation:
        raw = re.sub(r"\s+", " ", text.replace("’", "'")).strip()
        if not raw:
            return NaturalMemoryObservation()
        pending = self._pending_intent(session_id)
        lowered = raw.lower().rstrip(".!?")
        if pending and lowered in {"yes forget it", "confirm forget", "yes, forget it"}:
            self.control.forget(pending[2], confirmed=True, actor="explicit_user",
                                reason="Confirmed natural-language request")
            self._resolve_intent(pending[0], "completed")
            return NaturalMemoryObservation("forgotten", "Acknowledge briefly that the memory was forgotten.")
        if pending and lowered in {"no keep it", "cancel", "never mind", "no, keep it"}:
            self._resolve_intent(pending[0], "cancelled")
            return NaturalMemoryObservation("cancelled", "Acknowledge briefly that the memory was kept.")
        correction = re.match(r"^correct that to\s+(.+)$", raw, re.I)
        if correction:
            target = pending[2] if pending and pending[1] == "correct" else self._latest(session_id)
            if target is None:
                return NaturalMemoryObservation("not_found", "Say you could not identify a recent memory to correct.")
            content = self._stored_content(correction.group(1).strip(), ledger)
            self.control.correct_approved(target, content, actor="explicit_user",
                                          reason="Natural-language correction")
            if pending:
                self._resolve_intent(pending[0], "completed")
            return NaturalMemoryObservation("corrected", "Acknowledge the corrected memory naturally and briefly.", target)
        if lowered in {"that's not quite right", "that is not quite right"}:
            target = self._latest(session_id)
            if target is None:
                return NaturalMemoryObservation("not_found", "Ask which remembered detail needs correction.")
            self._create_intent(session_id, message_id, "correct", target)
            return NaturalMemoryObservation("confirm_correction", "Ask the user to say: Correct that to <the accurate detail>.", target)
        if re.match(r"^(?:don't remember|do not remember) (?:this|that)$", lowered):
            return NaturalMemoryObservation("excluded", "Acknowledge naturally; do not claim the raw chat message was deleted.")
        if re.match(r"^what have you remembered recently", lowered):
            recent = self.control.list_recent_natural(limit=8)
            summary = "\n".join(f"- {item['content']}" for item in recent) or "- Nothing yet."
            return NaturalMemoryObservation("recent", "Answer from this exact recent-memory list:\n" + summary)
        forget = re.match(
            r"^forget (?:(?:what i (?:said|shared)|the memory) about|about)\s+(.+)$",
            raw,
            re.I,
        )
        if forget or lowered in {"forget that", "don't remember that", "do not remember that"}:
            target = self._find_topic(forget.group(1)) if forget else self._latest(session_id)
            if target is None:
                return NaturalMemoryObservation("not_found", "Say you could not identify a matching semantic memory.")
            self._create_intent(session_id, message_id, "forget", target)
            item = self.control._get(target)
            return NaturalMemoryObservation("confirm_forget", f"Ask for one confirmation before forgetting this memory: {item[1]}", target)

        explicit = re.match(r"^remember(?: that)?\s+(.+)$", raw, re.I)
        candidate = explicit.group(1).strip() if explicit else raw
        if not explicit and (TRANSIENT.search(candidate) or not STABLE.search(candidate)):
            return NaturalMemoryObservation()
        if ledger == "mixed":
            return NaturalMemoryObservation()
        try:
            validate_persistable_text(candidate)
        except ValueError:
            return NaturalMemoryObservation("blocked", "Do not persist this message or reveal policy internals.")
        lane = ledger if ledger in {"story", "campaign"} else (
            "professional" if PROFESSIONAL.search(candidate) else "private_shared"
        )
        mode = "auto" if explicit else MemoryPolicyService(self.connection_factory).get_policy()[lane]
        if mode == "off":
            return NaturalMemoryObservation("off")
        stored = self._stored_content(candidate, ledger)
        duplicate = self._duplicate(stored, ledger)
        if duplicate is not None:
            return NaturalMemoryObservation("duplicate", memory_id=duplicate)
        result = self.corpus.propose_memory(
            stored,
            memory_type=ledger if ledger in {"story", "campaign"} else "fact",
            salience=6 if explicit else 5,
            metadata={
                "ledger": ledger,
                "trust_lane": lane,
                "approval_mode": "explicit" if explicit else mode,
                "source_type": "conversation",
                "source_id": str(message_id),
                "source_session_id": session_id,
                "source_message_id": message_id,
                "channel": channel,
                "proposal_reason": "Explicit user request" if explicit else f"Stable {lane} conversational context",
            },
        )
        memory_id = int(result["memory_id"])
        if mode == "auto":
            self.control.approve(memory_id, actor="explicit_user" if explicit else "memory_policy",
                                 details={"trust_lane": lane, "approval_mode": "explicit" if explicit else "auto"})
        instruction = "Acknowledge naturally that you will remember this." if explicit else None
        return NaturalMemoryObservation("approved" if mode == "auto" else "pending", instruction, memory_id)

    @staticmethod
    def _stored_content(text: str, ledger: str) -> str:
        prefix = {"story": "Story canon update: ", "campaign": "Campaign log: "}.get(ledger, "Christopher shared: ")
        return prefix + validate_persistable_text(text)

    def _duplicate(self, content: str, ledger: str) -> int | None:
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute("""SELECT id FROM memories WHERE lower(content)=lower(%s)
                           AND metadata->>'ledger'=%s AND review_status IN ('pending','approved')
                           ORDER BY id DESC LIMIT 1""", (content, ledger))
            row = cur.fetchone()
        return int(row[0]) if row else None

    def _latest(self, session_id: str) -> int | None:
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute("""SELECT id FROM memories WHERE review_status='approved'
                           AND metadata->>'source_session_id'=%s
                           AND metadata->>'approval_mode' IN ('auto','explicit')
                           ORDER BY created_at DESC,id DESC LIMIT 1""", (session_id,))
            row = cur.fetchone()
        return int(row[0]) if row else None

    def _find_topic(self, topic: str) -> int | None:
        terms = [term for term in re.findall(r"[A-Za-z0-9]+", topic) if len(term) > 2]
        if not terms:
            return None
        pattern = "%" + "%".join(terms) + "%"
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute("""SELECT id FROM memories WHERE review_status='approved'
                           AND metadata->>'destination_plane'='semantic_memory'
                           AND content ILIKE %s ORDER BY created_at DESC,id DESC LIMIT 1""", (pattern,))
            row = cur.fetchone()
        return int(row[0]) if row else None

    def _pending_intent(self, session_id: str) -> tuple[str, str, int] | None:
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute("""UPDATE memory_control_intents SET status='expired',resolved_at=now()
                           WHERE status='pending' AND expires_at<=now()""")
            cur.execute("""SELECT id,action,target_memory_id FROM memory_control_intents
                           WHERE session_id=%s AND status='pending' ORDER BY created_at DESC LIMIT 1""", (session_id,))
            row = cur.fetchone(); conn.commit()
        return (str(row[0]), row[1], int(row[2])) if row else None

    def _create_intent(self, session_id: str, message_id: int, action: str, target: int) -> None:
        expires = datetime.now(timezone.utc) + timedelta(minutes=self.intent_ttl_minutes)
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute("UPDATE memory_control_intents SET status='cancelled',resolved_at=now() WHERE session_id=%s AND status='pending'", (session_id,))
            cur.execute("""INSERT INTO memory_control_intents
                           (id,session_id,source_message_id,action,target_memory_id,expires_at)
                           VALUES (%s,%s,%s,%s,%s,%s)""",
                        (str(uuid.uuid4()), session_id, message_id, action, target, expires))
            conn.commit()

    def _resolve_intent(self, intent_id: str, status: str) -> None:
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute("UPDATE memory_control_intents SET status=%s,resolved_at=now() WHERE id=%s", (status, intent_id))
            conn.commit()

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import json
import re
from typing import Any, Callable

import numpy as np
import psycopg

from .db import connect
from .embeddings import EmbeddingService


def _vector_literal(vec: np.ndarray) -> str:
    return "[" + ",".join(f"{float(x):.8f}" for x in vec.tolist()) + "]"


def _normalize_sentence(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


_SENSITIVE_PATTERNS = [
    re.compile(r"\bxai-[A-Za-z0-9]{6,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{6,}\b"),
    re.compile(r"\bapi\s*key\b", re.I),
    re.compile(r"\bpassword\b", re.I),
    re.compile(r"\bconnection\s*string\b", re.I),
    re.compile(r"\bssn\b", re.I),
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    re.compile(r"\b\d{3}-\d{3}-\d{4}\b"),
    re.compile(r"\bmy\s+(friend|colleague|coworker|neighbor|family)\b", re.I),
    re.compile(r"\boff\s+the\s+record\b", re.I),
]


def _contains_sensitive(text: str) -> bool:
    lowered = text.lower()
    if "token" in lowered and "=" in lowered:
        return True
    return any(p.search(text) for p in _SENSITIVE_PATTERNS)


def _infer_ledger(sentence: str) -> str:
    s = sentence.lower()
    if any(k in s for k in ("campaign", "initiative", "encounter", "d20", "combat", "orc", "battle")):
        return "campaign"
    if any(k in s for k in ("ship", "phase regulator", "entanglement coil", "repair", "canon")):
        return "story"
    return "biography"


def _memory_type_for_ledger(ledger: str) -> str:
    if ledger == "story":
        return "story"
    if ledger == "campaign":
        return "campaign"
    return "fact"


@dataclass
class CandidateMemory:
    content: str
    ledger: str
    memory_type: str
    salience: int = 5
    metadata: dict[str, Any] | None = None


@dataclass
class MemoryService:
    embedding_service: EmbeddingService
    connection_factory: Callable[[], psycopg.Connection] = connect

    def summarize_transcript(self, transcript: str) -> list[CandidateMemory]:
        # Lightweight deterministic write-back summary logic for v1.
        raw_segments = re.split(r"[.\n]+", transcript)
        candidates: list[CandidateMemory] = []
        seen: set[str] = set()

        for seg in raw_segments:
            sentence = _normalize_sentence(seg)
            if len(sentence) < 16:
                continue
            if _contains_sensitive(sentence):
                continue
            canonical = sentence.lower()
            if canonical in seen:
                continue
            seen.add(canonical)

            ledger = _infer_ledger(sentence)
            prefixed = {
                "biography": f"Session note: {sentence}",
                "story": f"Story canon update: {sentence}",
                "campaign": f"Campaign log: {sentence}",
            }[ledger]
            candidates.append(
                CandidateMemory(
                    content=prefixed,
                    ledger=ledger,
                    memory_type=_memory_type_for_ledger(ledger),
                    salience=6 if ledger in {"story", "campaign"} else 5,
                    metadata={"ledger": ledger},
                )
            )
        return candidates

    def writeback_session(self, transcript: str) -> list[dict[str, Any]]:
        candidates = self.summarize_transcript(transcript)
        if not candidates:
            return []

        vectors = self.embedding_service.embed_texts([c.content for c in candidates])
        created: list[dict[str, Any]] = []

        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                for c, vec in zip(candidates, vectors):
                    meta = dict(c.metadata or {})
                    meta["writeback_at"] = datetime.now(timezone.utc).isoformat()
                    cur.execute(
                        """
                        INSERT INTO memories (content, embedding, memory_type, salience, metadata, approved)
                        VALUES (%s, %s::vector, %s, %s, %s::jsonb, false)
                        RETURNING id, approved
                        """,
                        (
                            c.content,
                            _vector_literal(vec),
                            c.memory_type,
                            c.salience,
                            json.dumps(meta),
                        ),
                    )
                    row = cur.fetchone()
                    created.append(
                        {
                            "memory_id": int(row[0]),
                            "approved": bool(row[1]),
                            "ledger": c.ledger,
                            "content": c.content,
                        }
                    )
            conn.commit()
        return created

    def approve_memory(self, memory_id: int) -> dict[str, Any]:
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE memories SET approved = true WHERE id = %s RETURNING id, approved",
                    (memory_id,),
                )
                row = cur.fetchone()
            conn.commit()
        if not row:
            raise ValueError(f"Memory id not found: {memory_id}")
        return {"memory_id": int(row[0]), "approved": bool(row[1])}

    def regenerate_story_canon(self, story_dir: str | Path = "agents/lyra/state/story") -> dict[str, Any]:
        story_path = Path(story_dir)
        story_path.mkdir(parents=True, exist_ok=True)

        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, content, created_at
                    FROM memories
                    WHERE approved = true
                      AND (
                        memory_type = 'story'
                        OR metadata->>'ledger' = 'story'
                      )
                    ORDER BY created_at ASC, id ASC
                    """
                )
                rows = cur.fetchall()

        lines = [row[1] for row in rows]
        timestamp = datetime.now(timezone.utc).isoformat()

        ship_items = [ln for ln in lines if any(k in ln.lower() for k in ("ship", "repair", "phase regulator", "coil"))]
        arcs_items = lines[-10:]
        timeline_items = [f"- {ln}" for ln in lines]

        ship_content = ["# Ship State (Story Canon)", ""]
        if ship_items:
            ship_content.extend(f"- {item}" for item in ship_items)
        else:
            ship_content.extend(
                [
                    "- Current condition: [No approved story updates yet]",
                    "- Major repairs: [No approved story updates yet]",
                    "- Blocking issues: [No approved story updates yet]",
                ]
            )
        ship_content.append(f"- Last updated from approved story memories: {timestamp}")
        ship_content.append("")

        arcs_content = ["# Story Arcs", ""]
        if arcs_items:
            arcs_content.extend(f"- {item}" for item in arcs_items)
        else:
            arcs_content.append("- [No approved story arcs yet]")
        arcs_content.append("")

        timeline_content = ["# Story Timeline", ""]
        if timeline_items:
            timeline_content.extend(timeline_items)
        else:
            timeline_content.append("- [No approved story milestones yet]")
        timeline_content.append("")

        (story_path / "ship.md").write_text("\n".join(ship_content), encoding="utf-8")
        (story_path / "arcs.md").write_text("\n".join(arcs_content), encoding="utf-8")
        (story_path / "timeline.md").write_text("\n".join(timeline_content), encoding="utf-8")

        return {"story_memory_count": len(lines), "output_dir": str(story_path)}

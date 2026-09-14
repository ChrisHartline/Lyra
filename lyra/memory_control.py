"""Local approval control plane for semantic memories and KG observations."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Callable

import psycopg

from .db import connect
from .embeddings import EmbeddingService
from .knowledge_graph import KnowledgeGraphWriter, ObservationService
from .memory import _vector_literal, sensitivity_flags, validate_persistable_text


LEDGERS = frozenset({"biography", "story", "campaign"})


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _destination(memory_type: str | None, metadata: dict[str, Any]) -> str:
    if memory_type == "observation" and metadata.get("plane") == "knowledge_graph":
        return "knowledge_graph"
    return "semantic_memory"


def _safe_reason(reason: str | None) -> str | None:
    return validate_persistable_text(reason) if reason is not None else None


def _validate_target(
    content: str,
    memory_type: str | None,
    metadata: dict[str, Any],
) -> tuple[str, str]:
    normalized = validate_persistable_text(content)
    destination = _destination(memory_type, metadata)
    ledger = str(metadata.get("ledger", "biography"))
    if ledger not in LEDGERS:
        raise ValueError("Unknown memory ledger")
    if memory_type in {"story", "campaign"} and ledger != memory_type:
        raise ValueError("Memory type and ledger do not match")
    if destination == "knowledge_graph" and ledger != "biography":
        raise ValueError("Knowledge-graph observations must use biography")
    return normalized, destination


@dataclass
class MemoryControlService:
    embedding_service: EmbeddingService
    graph_writer: KnowledgeGraphWriter
    connection_factory: Callable[[], psycopg.Connection] = connect

    def list_proposals(
        self,
        *,
        status: str = "pending",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if status not in {"pending", "approved"}:
            raise ValueError("Status must be pending or approved")
        bounded_limit = max(1, min(limit, 500))
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, content, memory_type, salience, metadata,
                           approved, review_status, created_at
                    FROM memories
                    WHERE review_status = %s
                    ORDER BY created_at DESC, id DESC
                    LIMIT %s
                    """,
                    (status, bounded_limit),
                )
                rows = cur.fetchall()
        proposals: list[dict[str, Any]] = []
        for row in rows:
            metadata = dict(row[4] or {})
            proposals.append(
                {
                    "proposal_id": int(row[0]),
                    "content": row[1],
                    "memory_type": row[2],
                    "ledger": metadata.get("ledger", "biography"),
                    "salience": int(row[3]),
                    "destination_plane": _destination(row[2], metadata),
                    "provenance": {
                        "source_type": metadata.get("source_type", "unknown"),
                        "source_id": metadata.get("source_id"),
                        "channel": metadata.get("channel"),
                    },
                    "sensitivity_flags": list(
                        metadata.get("sensitivity_flags") or []
                    ),
                    "proposal_reason": metadata.get(
                        "proposal_reason", "Legacy candidate"
                    ),
                    "approval_mode": metadata.get("approval_mode", "review"),
                    "trust_lane": metadata.get("trust_lane", "legacy_review"),
                    "approved": bool(row[5]),
                    "status": row[6],
                    "created_at": row[7],
                }
            )
        return proposals

    def approve(
        self,
        proposal_id: int,
        *,
        actor: str = "local_user",
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = self._get(proposal_id)
        if row[5] == "approved":
            return {
                "proposal_id": proposal_id,
                "status": "approved",
                "changed": False,
            }
        content, memory_type, metadata = row[1], row[2], dict(row[4] or {})
        _normalized, destination = _validate_target(
            content, memory_type, metadata
        )
        if destination == "knowledge_graph":
            result = ObservationService(
                embedding_service=self.embedding_service,
                graph_writer=self.graph_writer,
                connection_factory=self.connection_factory,
            ).approve_observation(proposal_id)
        else:
            with self.connection_factory() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE memories
                        SET approved = true, review_status = 'approved'
                        WHERE id = %s AND review_status = 'pending'
                        """,
                        (proposal_id,),
                    )
                    self._audit(
                        cur,
                        proposal_id,
                        destination,
                        "approved",
                        content,
                        actor=actor,
                        details=details,
                    )
                conn.commit()
            result = {"approved": True}
        if destination == "knowledge_graph":
            with self.connection_factory() as conn:
                with conn.cursor() as cur:
                    self._audit(
                        cur,
                        proposal_id,
                        destination,
                        "approved",
                        content,
                        actor=actor,
                        details=details,
                    )
                conn.commit()
        return {
            "proposal_id": proposal_id,
            "status": "approved",
            "changed": bool(result.get("approved", True)),
        }

    def correct(
        self,
        proposal_id: int,
        content: str,
        *,
        reason: str | None = None,
    ) -> dict[str, Any]:
        row = self._get(proposal_id)
        if row[5] != "pending":
            raise ValueError("Only pending proposals may be corrected")
        metadata = dict(row[4] or {})
        normalized, destination = _validate_target(content, row[2], metadata)
        reason = _safe_reason(reason)
        metadata["sensitivity_flags"] = sensitivity_flags(normalized)
        vector = self.embedding_service.embed_texts([normalized])[0]
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE memories
                    SET content = %s, embedding = %s::vector, metadata = %s::jsonb
                    WHERE id = %s AND review_status = 'pending'
                    """,
                    (
                        normalized,
                        _vector_literal(vector),
                        json.dumps(metadata),
                        proposal_id,
                    ),
                )
                self._audit(
                    cur,
                    proposal_id,
                    destination,
                    "corrected",
                    normalized,
                    reason=reason,
                    details={"previous_sha256": _content_hash(row[1])},
                )
            conn.commit()
        return {
            "proposal_id": proposal_id,
            "status": "pending",
            "content": normalized,
            "sensitivity_flags": metadata["sensitivity_flags"],
        }

    def correct_approved(
        self,
        proposal_id: int,
        content: str,
        *,
        reason: str | None = None,
        actor: str = "explicit_user",
    ) -> dict[str, Any]:
        row = self._get(proposal_id)
        if row[5] != "approved":
            raise ValueError("Only approved memories may be corrected conversationally")
        metadata = dict(row[4] or {})
        normalized, destination = _validate_target(content, row[2], metadata)
        if destination != "semantic_memory":
            raise ValueError("Natural-language correction cannot mutate KG observations")
        reason = _safe_reason(reason)
        metadata["sensitivity_flags"] = sensitivity_flags(normalized)
        metadata["last_control_mode"] = "natural_language"
        vector = self.embedding_service.embed_texts([normalized])[0]
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE memories
                    SET content = %s, embedding = %s::vector, metadata = %s::jsonb
                    WHERE id = %s AND review_status = 'approved'
                    """,
                    (
                        normalized,
                        _vector_literal(vector),
                        json.dumps(metadata),
                        proposal_id,
                    ),
                )
                self._audit(
                    cur,
                    proposal_id,
                    destination,
                    "corrected",
                    normalized,
                    actor=actor,
                    reason=reason,
                    details={"previous_sha256": _content_hash(row[1])},
                )
            conn.commit()
        return {
            "proposal_id": proposal_id,
            "status": "approved",
            "content": normalized,
            "sensitivity_flags": metadata["sensitivity_flags"],
        }

    def reject(self, proposal_id: int, *, reason: str) -> dict[str, Any]:
        reason = _safe_reason(reason)
        row = self._get(proposal_id)
        if row[5] != "pending":
            raise ValueError("Only pending proposals may be rejected")
        metadata = dict(row[4] or {})
        destination = _destination(row[2], metadata)
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                self._audit(
                    cur, proposal_id, destination, "rejected", row[1], reason=reason
                )
                cur.execute("DELETE FROM memories WHERE id = %s", (proposal_id,))
            conn.commit()
        return {"proposal_id": proposal_id, "status": "rejected"}

    def forget(
        self,
        proposal_id: int,
        *,
        confirmed: bool,
        reason: str | None = None,
        actor: str = "local_user",
    ) -> dict[str, Any]:
        if not confirmed:
            raise ValueError("Forget requires explicit confirmation")
        reason = _safe_reason(reason)
        row = self._get(proposal_id)
        if row[5] != "approved":
            raise ValueError("Only approved memories or observations may be forgotten")
        content, memory_type, metadata = row[1], row[2], dict(row[4] or {})
        destination = _destination(memory_type, metadata)
        if destination == "knowledge_graph":
            self.graph_writer.delete_observation(metadata["entity_name"], content)
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                self._audit(
                    cur,
                    proposal_id,
                    destination,
                    "forgotten",
                    content,
                    actor=actor,
                    reason=reason,
                )
                cur.execute("DELETE FROM memories WHERE id = %s", (proposal_id,))
            conn.commit()
        return {"proposal_id": proposal_id, "status": "forgotten"}

    def list_audit(self, *, limit: int = 200) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(limit, 1000))
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, proposal_id, destination_plane, action, actor,
                           reason, content_sha256, details, created_at
                    FROM memory_review_audit
                    ORDER BY created_at DESC, id DESC
                    LIMIT %s
                    """,
                    (bounded_limit,),
                )
                rows = cur.fetchall()
        return [
            {
                "audit_id": int(row[0]),
                "proposal_id": int(row[1]),
                "destination_plane": row[2],
                "action": row[3],
                "actor": row[4],
                "reason": row[5],
                "content_sha256": row[6],
                "details": row[7] or {},
                "created_at": row[8],
            }
            for row in rows
        ]

    def list_recent_natural(self, *, limit: int = 20) -> list[dict[str, Any]]:
        bounded = max(1, min(limit, 100))
        approved = self.list_proposals(status="approved", limit=500)
        return [
            item
            for item in approved
            if item["destination_plane"] == "semantic_memory"
            and item["approval_mode"] in {"auto", "explicit"}
        ][:bounded]

    def _get(self, proposal_id: int) -> tuple[Any, ...]:
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, content, memory_type, salience, metadata,
                           review_status
                    FROM memories WHERE id = %s
                    """,
                    (proposal_id,),
                )
                row = cur.fetchone()
        if not row:
            raise ValueError(f"Proposal id not found: {proposal_id}")
        return row

    @staticmethod
    def _audit(
        cursor: psycopg.Cursor,
        proposal_id: int,
        destination: str,
        action: str,
        content: str,
        *,
        actor: str = "local_user",
        reason: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        cursor.execute(
            """
            INSERT INTO memory_review_audit (
                proposal_id, destination_plane, action, actor, reason,
                content_sha256, details
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
            """,
            (
                proposal_id,
                destination,
                action,
                actor,
                reason,
                _content_hash(content),
                json.dumps(details or {}),
            ),
        )

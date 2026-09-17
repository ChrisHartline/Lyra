"""Opt-in, evidence-backed resurfacing across research and active work."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
import re
import uuid
from typing import Any, Callable, Iterable

import psycopg

from .away import AwayModeService
from .briefings import _is_story_or_campaign
from .db import connect
from .safety import safe_lines


_STOPWORDS = frozenset({
    "about", "after", "again", "also", "been", "before", "being", "could",
    "does", "from", "have", "into", "just", "more", "need", "only", "other",
    "should", "some", "than", "that", "their", "there", "these", "they", "this",
    "through", "using", "want", "what", "when", "where", "which", "while", "with",
    "would", "your",
})


@dataclass(frozen=True)
class GardenPolicy:
    enabled: bool
    channel: str
    interval_hours: int
    min_dormant_days: int
    max_suggestions: int
    last_run_at: datetime | None


@dataclass(frozen=True)
class GardenCandidate:
    fingerprint: str
    topic_key: str
    topic_label: str
    summary: str
    evidence: tuple[dict[str, Any], ...]
    score: int


@dataclass
class ResearchGardenService:
    away: AwayModeService
    connection_factory: Callable[[], psycopg.Connection] = connect

    def get_policy(self) -> GardenPolicy:
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute("""SELECT enabled,channel,interval_hours,min_dormant_days,
                max_suggestions,last_run_at FROM research_garden_policy
                WHERE singleton=true""")
            row = cur.fetchone()
        if not row:
            raise ValueError("Research Garden policy is not initialized")
        return GardenPolicy(*row)

    def policy_dict(self) -> dict[str, Any]:
        return asdict(self.get_policy())

    def set_policy(self, **values: Any) -> GardenPolicy:
        current = self.policy_dict()
        unknown = set(values) - set(current)
        if unknown:
            raise ValueError(f"Unknown Research Garden settings: {sorted(unknown)}")
        current.update(values)
        if current["channel"] not in {"web", "telegram"}:
            raise ValueError("Research Garden channel must be web or telegram")
        if not 1 <= int(current["interval_hours"]) <= 720:
            raise ValueError("Research Garden interval must be 1-720 hours")
        if not 1 <= int(current["min_dormant_days"]) <= 365:
            raise ValueError("Dormant age must be 1-365 days")
        if not 1 <= int(current["max_suggestions"]) <= 10:
            raise ValueError("Maximum suggestions must be 1-10")
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute("""UPDATE research_garden_policy SET enabled=%s,channel=%s,
                interval_hours=%s,min_dormant_days=%s,max_suggestions=%s,
                last_run_at=%s,updated_at=now() WHERE singleton=true""", (
                current["enabled"], current["channel"], current["interval_hours"],
                current["min_dormant_days"], current["max_suggestions"],
                current["last_run_at"],
            ))
            conn.commit()
        return self.get_policy()

    def discover(self, *, now: datetime | None = None, limit: int | None = None) -> list[GardenCandidate]:
        instant = _instant(now)
        policy = self.get_policy()
        maximum = min(10, max(1, limit or policy.max_suggestions))
        sources, questions, commitments = self._evidence(instant, policy.min_dormant_days)
        muted = self._muted_topics(instant)
        existing = self._existing_fingerprints()
        candidates: list[GardenCandidate] = []
        for left, right in (
            *((source, commitment) for source in sources for commitment in commitments),
            *((source, question) for source in sources for question in questions),
            *((commitment, question) for commitment in commitments for question in questions),
        ):
            shared = _shared_terms(left["match_text"], right["match_text"])
            if not shared:
                continue
            topic = sorted(shared, key=lambda term: (-len(term), term))[0]
            if topic in muted:
                continue
            evidence = tuple(_public_evidence(item) for item in (left, right))
            fingerprint = _fingerprint(evidence)
            if fingerprint in existing:
                continue
            candidates.append(GardenCandidate(
                fingerprint=fingerprint,
                topic_key=topic,
                topic_label=topic.replace("_", " ").title(),
                summary=_connection_summary(left, right),
                evidence=evidence,
                score=len(shared),
            ))
        deduped: dict[str, GardenCandidate] = {}
        for candidate in sorted(candidates, key=lambda item: (-item.score, item.topic_key, item.fingerprint)):
            deduped.setdefault(candidate.fingerprint, candidate)
        return list(deduped.values())[:maximum]

    def plan_due(self, *, now: datetime | None = None, force: bool = False) -> dict[str, Any]:
        instant = _instant(now)
        policy = self.get_policy()
        if not force and not policy.enabled:
            return {"disposition": "disabled"}
        if (not force and policy.last_run_at
                and instant < policy.last_run_at + timedelta(hours=policy.interval_hours)):
            return {"disposition": "not_due"}
        candidates = self.discover(now=instant, limit=policy.max_suggestions)
        self._mark_run(instant)
        if not candidates:
            return {"disposition": "no_candidates", "suggestions": []}
        body = self._render(candidates)
        decision = self.away.plan_notification(
            channel=policy.channel, category="research", content=body, now=instant
        )
        status = {"send": "planned", "batch": "batched", "suppress": "suppressed"}[
            decision.disposition
        ]
        suggestions = self._persist(candidates, status, policy.channel, body)
        return {"disposition": decision.disposition, "body": body,
                "suggestions": suggestions, "channel": policy.channel}

    def list_suggestions(self, *, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        clause = "WHERE status=%s" if status else ""
        params: tuple[Any, ...] = (status, min(200, max(1, limit))) if status else (min(200, max(1, limit)),)
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute(f"""SELECT id,fingerprint,topic_key,topic_label,summary,evidence,
                status,channel,session_id,created_at,delivered_at,dismissed_at
                FROM research_garden_suggestions {clause}
                ORDER BY created_at DESC LIMIT %s""", params)
            return [_suggestion(row) for row in cur.fetchall()]

    def dismiss(self, suggestion_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        instant = _instant(now)
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute("""UPDATE research_garden_suggestions
                SET status='dismissed',dismissed_at=%s WHERE id=%s
                RETURNING id,fingerprint,topic_key,topic_label,summary,evidence,status,
                          channel,session_id,created_at,delivered_at,dismissed_at""",
                (instant, suggestion_id))
            row = cur.fetchone(); conn.commit()
        if not row:
            raise ValueError("Research Garden suggestion not found")
        return _suggestion(row)

    def mute_topic(
        self, topic: str, *, expires_at: datetime | None = None, now: datetime | None = None
    ) -> dict[str, Any]:
        instant = _instant(now)
        key = _topic_key(topic)
        if expires_at is not None:
            expires_at = _instant(expires_at)
            if expires_at <= instant:
                raise ValueError("Topic mute expiry must be in the future")
        label = topic.strip()
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute("""INSERT INTO research_garden_topic_mutes
                (topic_key,topic_label,muted_at,expires_at) VALUES (%s,%s,%s,%s)
                ON CONFLICT(topic_key) DO UPDATE SET topic_label=EXCLUDED.topic_label,
                    muted_at=EXCLUDED.muted_at,expires_at=EXCLUDED.expires_at
                RETURNING topic_key,topic_label,muted_at,expires_at""",
                (key, label, instant, expires_at))
            row = cur.fetchone(); conn.commit()
        return {"topic_key": row[0], "topic_label": row[1],
                "muted_at": row[2], "expires_at": row[3]}

    def unmute_topic(self, topic: str) -> bool:
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM research_garden_topic_mutes WHERE topic_key=%s",
                        (_topic_key(topic),))
            removed = cur.rowcount == 1; conn.commit()
        return removed

    def list_mutes(self, *, now: datetime | None = None) -> list[dict[str, Any]]:
        instant = _instant(now)
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute("""SELECT topic_key,topic_label,muted_at,expires_at
                FROM research_garden_topic_mutes
                WHERE expires_at IS NULL OR expires_at>%s ORDER BY topic_key""", (instant,))
            return [{"topic_key": row[0], "topic_label": row[1],
                     "muted_at": row[2], "expires_at": row[3]} for row in cur.fetchall()]

    def draft_digest(self, suggestion_id: str) -> dict[str, Any]:
        matches = [item for item in self.list_suggestions(limit=200)
                   if item["suggestion_id"] == str(suggestion_id)]
        if not matches:
            raise ValueError("Research Garden suggestion not found")
        item = matches[0]
        citations = "\n".join(
            f"- [{evidence['plane']}:{evidence['id']}] {evidence['label']}"
            for evidence in item["evidence"]
        )
        body = (f"# Research Garden draft — {item['topic_label']}\n\n"
                "Conversational draft only. Nothing has been published.\n\n"
                f"## Connection\n{item['summary']}\n\n## Evidence\n{citations}\n")
        return {"suggestion_id": item["suggestion_id"], "body": body,
                "published": False}

    def mark_delivered(self, suggestion_ids: Iterable[str], *, session_id: str) -> None:
        ids = [uuid.UUID(value) for value in suggestion_ids]
        if not ids:
            return
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute("""UPDATE research_garden_suggestions SET status='delivered',
                session_id=%s,delivered_at=now() WHERE id=ANY(%s) AND status='planned'""",
                (session_id, ids))
            conn.commit()

    def mark_failed(self, suggestion_ids: Iterable[str]) -> None:
        ids = [uuid.UUID(value) for value in suggestion_ids]
        if not ids:
            return
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute("""UPDATE research_garden_suggestions SET status='failed'
                WHERE id=ANY(%s) AND status='planned'""", (ids,))
            conn.commit()

    def _evidence(self, now: datetime, dormant_days: int):
        cutoff = now - timedelta(days=dormant_days)
        sources: list[dict[str, Any]] = []
        questions: list[dict[str, Any]] = []
        commitments: list[dict[str, Any]] = []
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute("""SELECT s.id,COALESCE(s.title,s.url,s.file_path,'untitled'),
                s.url,s.fetched_at,COALESCE((SELECT string_agg(x.content,' ') FROM
                  (SELECT left(c.content,500) AS content FROM chunks c
                   WHERE c.source_id=s.id ORDER BY c.id LIMIT 3) x),'')
                FROM sources s WHERE s.superseded_by IS NULL
                ORDER BY s.fetched_at DESC,s.id DESC LIMIT 50""")
            for item_id, label, url, occurred_at, content in cur.fetchall():
                cleaned = safe_lines([f"{label} {content}"])
                if not cleaned:
                    continue
                sources.append(_evidence_item("source", item_id, str(label), occurred_at,
                                              cleaned[0], url=url))
            cur.execute("""SELECT m.id,m.session_id,m.content,m.created_at
                FROM session_messages m JOIN chat_sessions s ON s.id=m.session_id
                WHERE m.role='user' AND m.visible=true AND m.created_at<=%s
                  AND s.updated_at<=%s AND position('?' in m.content)>0
                  AND NOT EXISTS (
                    SELECT 1 FROM shared_journal_private_sessions p
                    WHERE p.session_id=s.id
                  )
                ORDER BY m.created_at DESC LIMIT 50""", (cutoff, cutoff))
            for item_id, session_id, content, occurred_at in cur.fetchall():
                cleaned = safe_lines([str(content)])
                if not cleaned or _is_story_or_campaign(cleaned[0]):
                    continue
                label = _clip(cleaned[0], 240)
                questions.append(_evidence_item("question", item_id, label, occurred_at,
                                                cleaned[0], session_id=str(session_id)))
            cur.execute("""SELECT id,summary,updated_at FROM commitments
                WHERE status='active' ORDER BY updated_at DESC LIMIT 50""")
            for item_id, summary, occurred_at in cur.fetchall():
                cleaned = safe_lines([str(summary)])
                if not cleaned:
                    continue
                commitments.append(_evidence_item("commitment", item_id, cleaned[0],
                                                  occurred_at, cleaned[0]))
        return sources, questions, commitments

    def _muted_topics(self, now: datetime) -> set[str]:
        return {item["topic_key"] for item in self.list_mutes(now=now)}

    def _existing_fingerprints(self) -> set[str]:
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute("SELECT fingerprint FROM research_garden_suggestions")
            return {str(row[0]) for row in cur.fetchall()}

    def _mark_run(self, instant: datetime) -> None:
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute("""UPDATE research_garden_policy SET last_run_at=%s,
                updated_at=now() WHERE singleton=true""", (instant,))
            conn.commit()

    def _persist(self, candidates: list[GardenCandidate], status: str,
                 channel: str, body: str) -> list[dict[str, Any]]:
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        rows = []
        with self.connection_factory() as conn, conn.cursor() as cur:
            for candidate in candidates:
                cur.execute("""INSERT INTO research_garden_suggestions
                    (id,fingerprint,topic_key,topic_label,summary,evidence,status,
                     channel,content_sha256) VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)
                    RETURNING id,fingerprint,topic_key,topic_label,summary,evidence,status,
                              channel,session_id,created_at,delivered_at,dismissed_at""", (
                    uuid.uuid4(), candidate.fingerprint, candidate.topic_key,
                    candidate.topic_label, candidate.summary,
                    json.dumps(candidate.evidence, default=str), status, channel, digest,
                ))
                rows.append(_suggestion(cur.fetchone()))
            conn.commit()
        return rows

    @staticmethod
    def _render(candidates: list[GardenCandidate]) -> str:
        lines = ["Research Garden found a few evidence-backed connections—not new commitments.", ""]
        for candidate in candidates:
            citations = " ".join(
                f"[{item['plane']}:{item['id']}]" for item in candidate.evidence
            )
            lines.append(f"- {candidate.summary} {citations}")
        lines.extend(["", "Want to explore one, dismiss it, or mute a topic?"])
        return "\n".join(lines)


def _instant(value: datetime | None) -> datetime:
    instant = value or datetime.now(UTC)
    if instant.tzinfo is None:
        raise ValueError("Research Garden time must be timezone-aware")
    return instant.astimezone(UTC)


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9_]+", text.lower())
            if len(token) >= 4 and token not in _STOPWORDS and not token.isdigit()}


def _shared_terms(left: str, right: str) -> set[str]:
    shared = _tokens(left) & _tokens(right)
    return shared if len(shared) >= 2 or any(len(term) >= 7 for term in shared) else set()


def _topic_key(value: str) -> str:
    tokens = sorted(_tokens(value), key=lambda token: (-len(token), token))
    if not tokens:
        raise ValueError("Topic must contain a meaningful word")
    return tokens[0]


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _evidence_item(plane: str, item_id: Any, label: str, occurred_at: datetime,
                   match_text: str, **extra: Any) -> dict[str, Any]:
    return {"plane": plane, "id": str(item_id), "label": label,
            "occurred_at": occurred_at, "match_text": match_text, **extra}


def _public_evidence(item: dict[str, Any]) -> dict[str, Any]:
    return {key: (value.isoformat() if isinstance(value, datetime) else value)
            for key, value in item.items() if key != "match_text" and value is not None}


def _fingerprint(evidence: Iterable[dict[str, Any]]) -> str:
    identities = sorted(f"{item['plane']}:{item['id']}" for item in evidence)
    return hashlib.sha256("|".join(identities).encode("utf-8")).hexdigest()


def _connection_summary(left: dict[str, Any], right: dict[str, Any]) -> str:
    labels = {left["plane"]: left["label"], right["plane"]: right["label"]}
    if "source" in labels and "commitment" in labels:
        return f'A saved source (“{labels["source"]}”) may support the active commitment “{labels["commitment"]}”.'
    if "source" in labels and "question" in labels:
        return f'The dormant question “{labels["question"]}” may connect to “{labels["source"]}”.'
    return f'The dormant question “{labels["question"]}” overlaps the active commitment “{labels["commitment"]}”.'


def _suggestion(row: Any) -> dict[str, Any]:
    return {"suggestion_id": str(row[0]), "fingerprint": row[1], "topic_key": row[2],
            "topic_label": row[3], "summary": row[4], "evidence": row[5] or [],
            "status": row[6], "channel": row[7],
            "session_id": str(row[8]) if row[8] else None, "created_at": row[9],
            "delivered_at": row[10], "dismissed_at": row[11]}

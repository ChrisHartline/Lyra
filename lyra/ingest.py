from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import json
import re
import shutil
from typing import Callable

import numpy as np
import psycopg
import requests
from docx import Document
from pypdf import PdfReader

from .db import connect
from .embeddings import EmbeddingService


def _normalize_text(text: str) -> str:
    return " ".join(text.split()).strip().lower()


def _content_hash(text: str) -> str:
    return sha256(_normalize_text(text).encode("utf-8")).hexdigest()


def _chunk_text(text: str, chunk_size: int = 800, overlap: int = 120) -> list[str]:
    normalized = " ".join(text.split())
    if not normalized:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(start + chunk_size, len(normalized))
        chunks.append(normalized[start:end])
        if end == len(normalized):
            break
        start = max(0, end - overlap)
    return chunks


def _strip_html(html: str) -> str:
    text = re.sub(r"<script.*?>.*?</script>", " ", html, flags=re.I | re.S)
    text = re.sub(r"<style.*?>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _vector_literal(vec: np.ndarray) -> str:
    return "[" + ",".join(f"{float(x):.8f}" for x in vec.tolist()) + "]"


def _format_name(path: Path) -> str:
    ext = path.suffix.lower().lstrip(".")
    return ext if ext else "unknown"


def _format_score(fmt: str) -> int:
    # Preference: native text/docx/html > born-digital pdf > unknown.
    if fmt in {"md", "txt", "html", "htm", "docx"}:
        return 3
    if fmt == "pdf":
        return 2
    return 1


@dataclass
class IngestResult:
    source_id: int
    active_source_id: int
    was_deduped: bool


class IngestPipeline:
    def __init__(
        self,
        embedding_service: EmbeddingService | None = None,
        connection_factory: Callable[[], psycopg.Connection] = connect,
        raw_root: str | Path = "data/raw",
    ) -> None:
        self.embedding_service = embedding_service or EmbeddingService()
        self.connection_factory = connection_factory
        self.raw_root = Path(raw_root)
        self.raw_root.mkdir(parents=True, exist_ok=True)

    def ingest_url(self, url: str, title: str | None = None) -> IngestResult:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        body = _strip_html(resp.text)
        resolved_title = title or url
        raw_path = self._write_raw_url(url, resp.text)
        return self._upsert_source_and_chunks(
            source_url=url,
            source_path=raw_path,
            title=resolved_title,
            text=body,
            source_kind="url",
            fmt="html",
            original_ref=url,
        )

    def ingest_file(self, local_path: str | Path, title: str | None = None) -> IngestResult:
        src = Path(local_path)
        if not src.exists():
            raise FileNotFoundError(src)
        fmt = _format_name(src)
        text = self._extract_file_text(src, fmt)
        raw_path = self._copy_raw_file(src)
        resolved_title = title or src.stem
        return self._upsert_source_and_chunks(
            source_url=None,
            source_path=raw_path,
            title=resolved_title,
            text=text,
            source_kind="file",
            fmt=fmt,
            original_ref=str(src),
        )

    def _write_raw_url(self, url: str, body: str) -> Path:
        key = sha256(url.encode("utf-8")).hexdigest()[:16]
        path = self.raw_root / f"url_{key}.html"
        path.write_text(body, encoding="utf-8")
        return path

    def _copy_raw_file(self, src: Path) -> Path:
        key = sha256(str(src).encode("utf-8")).hexdigest()[:12]
        dest = self.raw_root / f"{key}_{src.name}"
        shutil.copy2(src, dest)
        return dest

    def _extract_file_text(self, src: Path, fmt: str) -> str:
        if fmt == "docx":
            doc = Document(str(src))
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        if fmt == "pdf":
            try:
                reader = PdfReader(str(src))
                extracted = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
                if extracted:
                    return extracted
            except Exception:
                pass
            # Test/local fallback for malformed pseudo-pdf content.
            return src.read_text(encoding="utf-8", errors="ignore")
        return src.read_text(encoding="utf-8", errors="ignore")

    def _upsert_source_and_chunks(
        self,
        source_url: str | None,
        source_path: Path,
        title: str,
        text: str,
        source_kind: str,
        fmt: str,
        original_ref: str,
    ) -> IngestResult:
        normalized = _normalize_text(text)
        if not normalized:
            normalized = title
        content_hash = _content_hash(normalized)
        metadata = {
            "content_hash": content_hash,
            "format": fmt,
            "source_kind": source_kind,
            "original_ref": original_ref,
        }

        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, metadata
                    FROM sources
                    WHERE superseded_by IS NULL
                      AND metadata->>'content_hash' = %s
                    ORDER BY id
                    LIMIT 1
                    """,
                    (content_hash,),
                )
                existing = cur.fetchone()

                if existing:
                    existing_id = int(existing[0])
                    existing_meta = existing[1] or {}
                    existing_fmt = str(existing_meta.get("format", "unknown"))
                    existing_score = _format_score(existing_fmt)
                    new_score = _format_score(fmt)

                    if new_score <= existing_score:
                        # Same or worse format: keep existing active source.
                        if new_score < existing_score:
                            cur.execute(
                                """
                                INSERT INTO sources (url, file_path, title, metadata, superseded_by)
                                VALUES (%s, %s, %s, %s::jsonb, %s)
                                RETURNING id
                                """,
                                (
                                    source_url,
                                    str(source_path),
                                    title,
                                    json.dumps(metadata),
                                    existing_id,
                                ),
                            )
                            new_id = int(cur.fetchone()[0])
                            conn.commit()
                            return IngestResult(new_id, existing_id, True)
                        conn.commit()
                        return IngestResult(existing_id, existing_id, True)

                # Insert new active source.
                cur.execute(
                    """
                    INSERT INTO sources (url, file_path, title, metadata)
                    VALUES (%s, %s, %s, %s::jsonb)
                    RETURNING id
                    """,
                    (source_url, str(source_path), title, json.dumps(metadata)),
                )
                new_id = int(cur.fetchone()[0])

                chunks = _chunk_text(normalized)
                vectors = self.embedding_service.embed_texts(chunks) if chunks else np.zeros((0, 384), dtype=np.float32)
                for chunk, vec in zip(chunks, vectors):
                    cur.execute(
                        """
                        INSERT INTO chunks (source_id, content, embedding)
                        VALUES (%s, %s, %s::vector)
                        """,
                        (new_id, chunk, _vector_literal(vec)),
                    )

                if existing:
                    old_id = int(existing[0])
                    cur.execute("DELETE FROM chunks WHERE source_id = %s", (old_id,))
                    cur.execute("UPDATE sources SET superseded_by = %s WHERE id = %s", (new_id, old_id))
                    conn.commit()
                    return IngestResult(new_id, new_id, True)

                conn.commit()
                return IngestResult(new_id, new_id, False)

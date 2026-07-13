from __future__ import annotations

from pathlib import Path
import shutil
import uuid

import numpy as np
import psycopg
import responses
from docx import Document

from lyra.ingest import IngestPipeline

TEST_DB = {
    "host": "127.0.0.1",
    "port": 55432,
    "dbname": "lyra",
    "user": "lyra",
    "password": "lyra",
}


def _conn():
    return psycopg.connect(**TEST_DB, connect_timeout=3)


def _reset_tables() -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(Path("db/schema.sql").read_text(encoding="utf-8"))
            cur.execute("TRUNCATE chunks, sources, memories RESTART IDENTITY CASCADE")
        conn.commit()


class FakeEmbedder:
    def embed_texts(self, texts):
        out = []
        for i, _ in enumerate(texts):
            v = np.zeros(384, dtype=np.float32)
            v[i % 384] = 1.0
            out.append(v)
        return np.array(out)


def _pipeline(tmp_path: Path) -> IngestPipeline:
    return IngestPipeline(
        embedding_service=FakeEmbedder(),
        connection_factory=_conn,
        raw_root=tmp_path / "raw",
    )


def _case_dir(name: str) -> Path:
    root = Path("data/test_tmp")
    root.mkdir(parents=True, exist_ok=True)
    case = root / f"{name}_{uuid.uuid4().hex[:8]}"
    case.mkdir(parents=True, exist_ok=True)
    return case


@responses.activate
def test_a3_ingest_url_and_pdf_with_provenance(ensure_db):
    _reset_tables()
    case = _case_dir("a3_url_pdf")
    pipe = _pipeline(case)

    url = "https://example.com/article"
    html = "<html><body><h1>Quantum circuit notes</h1><p>QNN ansatz details.</p></body></html>"
    responses.add(responses.GET, url, body=html, status=200)

    pseudo_pdf = case / "ship_notes.pdf"
    pseudo_pdf.write_text("Ship phase regulator diagnostics and repair checklist", encoding="utf-8")

    url_result = pipe.ingest_url(url, title="Quantum Article")
    pdf_result = pipe.ingest_file(pseudo_pdf, title="Ship Notes")

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, url, file_path FROM sources WHERE id = %s", (url_result.source_id,))
            url_row = cur.fetchone()
            assert url_row[1] == url
            assert Path(url_row[2]).exists()

            cur.execute("SELECT id, url, file_path FROM sources WHERE id = %s", (pdf_result.source_id,))
            pdf_row = cur.fetchone()
            assert pdf_row[1] is None
            assert Path(pdf_row[2]).exists()

            cur.execute("SELECT COUNT(*) FROM chunks WHERE source_id = %s", (url_result.source_id,))
            assert cur.fetchone()[0] >= 1
            cur.execute(
                "SELECT COUNT(*) FROM chunks WHERE source_id = %s AND embedding IS NOT NULL",
                (url_result.source_id,),
            )
            assert cur.fetchone()[0] >= 1

            cur.execute("SELECT COUNT(*) FROM chunks WHERE source_id = %s", (pdf_result.source_id,))
            assert cur.fetchone()[0] >= 1
            cur.execute(
                "SELECT COUNT(*) FROM chunks WHERE source_id = %s AND embedding IS NOT NULL",
                (pdf_result.source_id,),
            )
            assert cur.fetchone()[0] >= 1
    shutil.rmtree(case, ignore_errors=True)


def test_a3_dedup_same_article_pdf_docx_and_repeat(ensure_db):
    _reset_tables()
    case = _case_dir("a3_dedup")
    pipe = _pipeline(case)

    article_text = "Quantum circuit stability and QNN ansatz tuning."
    pdf_path = case / "article.pdf"
    pdf_path.write_text(article_text, encoding="utf-8")  # pseudo-pdf fallback path

    docx_path = case / "article.docx"
    doc = Document()
    doc.add_paragraph(article_text)
    doc.save(str(docx_path))

    first_pdf = pipe.ingest_file(pdf_path, title="article")
    docx_result = pipe.ingest_file(docx_path, title="article")
    repeat_docx = pipe.ingest_file(docx_path, title="article")

    assert repeat_docx.active_source_id == docx_result.active_source_id

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, metadata, superseded_by
                FROM sources
                WHERE title = 'article'
                ORDER BY id
                """
            )
            rows = cur.fetchall()
            assert len(rows) >= 2

            active_rows = [r for r in rows if r[2] is None]
            assert len(active_rows) == 1
            active_id = int(active_rows[0][0])
            active_fmt = (active_rows[0][1] or {}).get("format")
            assert active_fmt == "docx"

            superseded = [r for r in rows if (r[1] or {}).get("format") == "pdf"]
            assert superseded, "Expected a superseded pdf source row"
            superseded_id = int(superseded[0][0])
            assert superseded[0][2] == active_id

            cur.execute("SELECT COUNT(*) FROM chunks WHERE source_id = %s", (superseded_id,))
            assert cur.fetchone()[0] == 0

            cur.execute("SELECT COUNT(*) FROM sources WHERE title = 'article' AND superseded_by IS NULL")
            assert cur.fetchone()[0] == 1

            # Original PDF row should now be superseded by the preferred DOCX row.
            assert first_pdf.source_id == superseded_id
    shutil.rmtree(case, ignore_errors=True)

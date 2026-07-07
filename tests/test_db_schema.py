from __future__ import annotations

from pathlib import Path
import numpy as np
import psycopg
from pgvector.psycopg import register_vector

TEST_DB = {
    "host": "127.0.0.1",
    "port": 55432,
    "dbname": "lyra",
    "user": "lyra",
    "password": "lyra",
}


def _conn():
    return psycopg.connect(
        **TEST_DB,
        connect_timeout=3,
    )


def test_a1_schema_and_cosine_similarity(ensure_db):
    schema = Path("db/schema.sql").read_text(encoding="utf-8")
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(schema)
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        register_vector(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT extname FROM pg_extension WHERE extname = 'vector'")
            assert cur.fetchone()[0] == "vector"

            for tbl in ("sources", "chunks", "memories"):
                cur.execute("SELECT to_regclass(%s)", (f"public.{tbl}",))
                assert cur.fetchone()[0] in (f"public.{tbl}", tbl)

            cur.execute("TRUNCATE chunks, sources, memories RESTART IDENTITY CASCADE")
            cur.execute("INSERT INTO sources (url, file_path, title) VALUES (%s,%s,%s) RETURNING id", ("https://example.com", "data/example.txt", "Example"))
            source_id = cur.fetchone()[0]

            base = np.zeros(384, dtype=np.float32)
            base[0] = 1.0
            near = np.zeros(384, dtype=np.float32)
            near[0] = 0.95
            near[1] = 0.05

            cur.execute(
                "INSERT INTO chunks (source_id, content, embedding) VALUES (%s,%s,%s),(%s,%s,%s)",
                (source_id, "base", base.tolist(), source_id, "near", near.tolist()),
            )

            cur.execute(
                """
                SELECT content
                FROM chunks
                ORDER BY embedding <=> %s::vector
                LIMIT 1
                """,
                (base.tolist(),),
            )
            top = cur.fetchone()[0]
            assert top == "base"
        conn.commit()

"""One-time-safe provenance backfill for pre-hardening commitments."""

from __future__ import annotations

from lyra.db import connect


def main() -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """UPDATE commitment_candidates
               SET visibility_scope='professional'
               WHERE visibility_scope='general' AND source_type='dashboard'"""
        )
        dashboard = cur.rowcount
        cur.execute(
            """UPDATE commitment_candidates c
               SET visibility_scope='professional'
               FROM chat_sessions s
               WHERE c.source_session_id=s.id
                 AND c.visibility_scope='general'
                 AND s.context_scope='professional'"""
        )
        professional = cur.rowcount
        cur.execute(
            """UPDATE commitment_candidates c
               SET visibility_scope='private_shared'
               FROM shared_journal_private_sessions p
               WHERE c.source_session_id=p.session_id
                 AND c.visibility_scope<>'private_shared'"""
        )
        private = cur.rowcount
        cur.execute(
            """UPDATE commitments c
               SET visibility_scope=o.visibility_scope,updated_at=c.updated_at
               FROM commitment_candidates o
               WHERE c.candidate_id=o.id
                 AND c.visibility_scope<>o.visibility_scope"""
        )
        confirmed = cur.rowcount
        conn.commit()
    print(
        "Commitment scope backfill: "
        f"dashboard={dashboard}, professional={professional}, "
        f"private={private}, confirmed={confirmed}"
    )


if __name__ == "__main__":
    main()

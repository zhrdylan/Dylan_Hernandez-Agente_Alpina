from uuid import uuid4

from psycopg import sql

from app.db.connection import connect
from app.db.migrate import verify_schema, check_database_ready


def test_schema_verification_reports_and_chats():
    with connect() as conn:
        status = verify_schema(conn)
        assert status["ready"] is True
        assert "chats" in status["tables"]
        assert "session_id" in status["chats_columns"]
        assert "reports" in status["tables"]
        assert "session_id" in status["reports_columns"]
        assert status["reports_docx_supported"] is True


def test_check_database_ready_callable():
    ready, details = check_database_ready()
    assert ready is True
    assert details.get("ready") is True


def test_rls_scopes_chats_messages_reports_and_audit_events():
    owner, other = (f"owner_{uuid4().hex}" for _ in range(2))
    with connect(session_id=owner) as conn:
        chat_id = conn.execute("insert into public.chats (session_id) values (%s) returning id", (owner,)).fetchone()[0]
        message_id = conn.execute(
            "insert into public.messages (chat_id, role, content) values (%s, 'user', '') returning id", (chat_id,),
        ).fetchone()[0]
        conn.execute(
            "insert into public.reports (chat_id, session_id, report_type, title) values (%s, %s, 'pdf', 'Prueba')",
            (chat_id, owner),
        )
        conn.execute(
            "insert into public.audit_events (chat_id, message_id, event_type) values (%s, %s, 'prueba')",
            (chat_id, message_id),
        )

    try:
        for session_id, expected_count in ((None, 0), (other, 0), (owner, 1)):
            with connect(session_id=session_id) as conn:
                for table, column in (("chats", "id"), ("messages", "chat_id"), ("reports", "chat_id"), ("audit_events", "chat_id")):
                    query = sql.SQL("select count(*) from public.{} where {} = %s").format(
                        sql.Identifier(table), sql.Identifier(column),
                    )
                    assert conn.execute(query, (chat_id,)).fetchone() == (expected_count,), table
    finally:
        with connect(session_id=owner) as conn:
            conn.execute("delete from public.audit_events where chat_id = %s", (chat_id,))
            conn.execute("delete from public.reports where chat_id = %s", (chat_id,))
            conn.execute("delete from public.chats where id = %s", (chat_id,))

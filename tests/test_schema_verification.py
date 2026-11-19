import pytest
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

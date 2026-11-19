from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
import psycopg
from psycopg.rows import dict_row

from app.db.connection import connect

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def get_migration_files() -> list[Path]:
    """Obtiene los archivos SQL de migración ordenados lexicográficamente."""
    if not MIGRATIONS_DIR.is_dir():
        return []
    return sorted(MIGRATIONS_DIR.glob("*.sql"), key=lambda p: p.name)


def apply_migrations(conn: psycopg.Connection) -> list[str]:
    """Aplica las migraciones pendientes registrándolas en schema_migrations."""
    applied: list[str] = []
    with conn.cursor() as cur:
        cur.execute(
            """
            create table if not exists public.schema_migrations (
                version text primary key,
                applied_at timestamptz not null default now()
            );
            """
        )
        cur.execute("select version from public.schema_migrations;")
        already_applied = {row[0] for row in cur.fetchall()}

    for sql_file in get_migration_files():
        version = sql_file.name
        if version in already_applied:
            continue

        logger.info("Aplicando migración: %s", version)
        sql_content = sql_file.read_text(encoding="utf-8")
        try:
            with conn.cursor() as cur:
                cur.execute(sql_content)
                cur.execute(
                    "insert into public.schema_migrations (version) values (%s);",
                    (version,),
                )
            conn.commit()
            applied.append(version)
            logger.info("Migración aplicada exitosamente: %s", version)
        except Exception as exc:
            conn.rollback()
            logger.error("Error aplicando migración %s: %s", version, exc)
            raise RuntimeError(f"Fallo en migración {version}: {exc}") from exc

    return applied


def verify_schema(conn: psycopg.Connection) -> dict[str, Any]:
    """Verifica que el esquema de la base de datos cumpla con todos los contratos requeridos."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            select table_name
            from information_schema.tables
            where table_schema = 'public';
            """
        )
        tables = {row["table_name"] for row in cur.fetchall()}

        # Verificar columnas de chats
        cur.execute(
            """
            select column_name
            from information_schema.columns
            where table_schema = 'public' and table_name = 'chats';
            """
        )
        chats_cols = {row["column_name"] for row in cur.fetchall()}

        # Verificar columnas de reports
        cur.execute(
            """
            select column_name
            from information_schema.columns
            where table_schema = 'public' and table_name = 'reports';
            """
        )
        reports_cols = {row["column_name"] for row in cur.fetchall()}

        # Verificar soporte docx en la restricción de reports
        cur.execute(
            """
            select pg_get_constraintdef(oid) as def
            from pg_constraint
            where conrelid = 'public.reports'::regclass
              and conname = 'reports_report_type_check';
            """
        )
        row_c = cur.fetchone()
        c_def = str(row_c["def"]) if row_c and row_c.get("def") else ""
        docx_supported = "docx" in c_def

    required_tables = {"documents", "document_versions", "chats", "messages", "reports"}
    missing_tables = required_tables - tables

    ready = (
        len(missing_tables) == 0
        and "session_id" in chats_cols
        and "user_id" in chats_cols
        and "session_id" in reports_cols
        and docx_supported
    )

    return {
        "ready": ready,
        "tables": list(tables),
        "missing_tables": list(missing_tables),
        "chats_columns": list(chats_cols),
        "reports_columns": list(reports_cols),
        "reports_docx_supported": docx_supported,
    }


def check_database_ready() -> tuple[bool, dict[str, Any]]:
    """Comprueba de forma rápida y segura la disponibilidad y coherencia del esquema."""
    try:
        with connect() as conn:
            status = verify_schema(conn)
            return status["ready"], status
    except Exception as exc:
        return False, {"error": f"{type(exc).__name__}: {exc}"}


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    logger.info("Iniciando verificación y migración de base de datos...")
    with connect() as conn:
        applied = apply_migrations(conn)
        if applied:
            logger.info("Migraciones aplicadas: %s", ", ".join(applied))
        else:
            logger.info("No hay migraciones pendientes.")
        status = verify_schema(conn)
        if status["ready"]:
            logger.info("Esquema verificado y 100%% operacional.")
        else:
            logger.warning("El esquema presenta inconsistencias: %s", status)


if __name__ == "__main__":
    main()

from __future__ import annotations

import atexit
from contextlib import contextmanager
from threading import Lock
from typing import Iterator

import psycopg
from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool

from app.config import settings


class DatabaseConfigError(RuntimeError):
    pass


_pool: ConnectionPool | None = None
_pool_lock = Lock()


def _configure(connection: psycopg.Connection) -> None:
    connection.autocommit = False
    try:
        register_vector(connection)
    except psycopg.ProgrammingError:
        # La extensión todavía puede estar pendiente en una base sin migrar.
        pass


def verify_web_role(connection: psycopg.Connection) -> None:
    role = connection.execute(
        """
        select rolname, rolsuper, rolbypassrls from pg_roles where rolname = current_user
        """
    ).fetchone()
    if role != ("alpina_app", False, False):
        raise DatabaseConfigError("DATABASE_URL debe usar el rol alpina_app sin privilegios de omisión de RLS.")


def _get_pool() -> ConnectionPool:
    global _pool
    with _pool_lock:
        if _pool is None:
            if not settings.database_url:
                raise DatabaseConfigError(
                    "DATABASE_URL no está configurada en el archivo .env."
                )
            pool = ConnectionPool(
                conninfo=settings.database_url,
                min_size=1,
                max_size=10,
                timeout=15,
                kwargs={
                    "connect_timeout": 15,
                    "prepare_threshold": None,
                },
                configure=_configure,
                open=False,
            )
            try:
                pool.open(wait=True, timeout=20)
                with pool.connection() as connection:
                    verify_web_role(connection)
            except Exception:
                pool.close()
                raise
            _pool = pool
        return _pool


def bind_session(connection: psycopg.Connection, session_id: str | None) -> None:
    connection.execute("select set_config('app.current_session_id', %s, true)", (session_id or "",))


@contextmanager
def connect(*, session_id: str | None = None) -> Iterator[psycopg.Connection]:
    with _get_pool().connection() as connection:
        bind_session(connection, session_id)
        yield connection


def warm_pool() -> None:
    pool = _get_pool()
    with pool.connection() as connection:
        with connection.cursor() as cur:
            cur.execute("select 1")


def close_pool() -> None:
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.close()
            _pool = None


atexit.register(close_pool)

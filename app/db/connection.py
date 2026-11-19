from __future__ import annotations

import atexit
from contextlib import contextmanager
from typing import Iterator

import psycopg
from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool

from app.config import settings


class DatabaseConfigError(RuntimeError):
    pass


_pool: ConnectionPool | None = None


def _configure(connection: psycopg.Connection) -> None:
    connection.autocommit = False
    register_vector(connection)


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        if not settings.database_url:
            raise DatabaseConfigError(
                "DATABASE_URL no está configurada en el archivo .env."
            )
        _pool = ConnectionPool(
            conninfo=settings.database_url,
            min_size=1,
            max_size=10,
            timeout=15,
            kwargs={
                "connect_timeout": 15,
                "prepare_threshold": 0,
            },
            configure=_configure,
            open=False,
        )
        _pool.open(wait=True, timeout=20)
    return _pool


@contextmanager
def connect(*, autocommit: bool = False) -> Iterator[psycopg.Connection]:
    pool = _get_pool()
    with pool.connection() as connection:
        if autocommit:
            connection.autocommit = True
        try:
            yield connection
        finally:
            if autocommit:
                connection.autocommit = False


def warm_pool() -> None:
    pool = _get_pool()
    with pool.connection() as connection:
        with connection.cursor() as cur:
            cur.execute("select 1")


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


atexit.register(close_pool)

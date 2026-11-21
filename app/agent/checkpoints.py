from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.encrypted import EncryptedSerializer
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg import Connection, sql
from psycopg_pool import ConnectionPool

from app.core.crypto import get_fernet
from app.db.connection import bind_session

_CHECKPOINT_TABLES = ("checkpoints", "checkpoint_blobs", "checkpoint_writes")
_checkpoint_owner: ContextVar[str | None] = ContextVar("checkpoint_owner", default=None)


@contextmanager
def checkpoint_session(session_id: str | None) -> Iterator[None]:
    token = _checkpoint_owner.set(session_id)
    try:
        yield
    finally:
        _checkpoint_owner.reset(token)


class CheckpointPool(ConnectionPool):
    @contextmanager
    def connection(self, timeout: float | None = None) -> Iterator[Connection]:
        with super().connection(timeout=timeout) as conn:
            owner = _checkpoint_owner.get()
            if owner is None:
                yield conn
            else:
                with conn.transaction():
                    bind_session(conn, owner)
                    yield conn


def setup_checkpointer(saver: PostgresSaver, pool: ConnectionPool) -> None:
    # LangGraph crea sus tablas e índices en el search_path del rol web.
    saver.setup()
    with pool.connection() as conn, conn.transaction():
        for table in _CHECKPOINT_TABLES:
            if conn.execute(
                """
                select 1 from pg_class as c join pg_policy as p on p.polrelid = c.oid
                where c.oid = to_regclass(%s) and c.relrowsecurity and c.relforcerowsecurity
                  and p.polname = 'alpina_checkpoint_owner' and not p.polpermissive
                """,
                (table,),
            ).fetchone():
                continue
            conn.execute(sql.SQL("""
                alter table {table} enable row level security;
                alter table {table} force row level security;
                drop policy if exists alpina_checkpoint_app on {table};
                create policy alpina_checkpoint_app on {table} for all to alpina_app using (true);
                drop policy if exists alpina_checkpoint_owner on {table};
                create policy alpina_checkpoint_owner on {table} as restrictive for all to public
                using (exists (select from public.chats where id::text = thread_id))
                with check (exists (select from public.chats where id::text = thread_id for key share));
            """).format(table=sql.Identifier(table)), prepare=False)


def delete_chat_checkpoints(conn: Connection, chat_id: str) -> None:
    tables = conn.execute(
        "select name from unnest(%s::text[]) as name where to_regclass(name) is not null",
        (list(_CHECKPOINT_TABLES),),
    ).fetchall()
    for (table,) in tables:
        conn.execute(sql.SQL("delete from {} where thread_id = %s").format(sql.Identifier(table)), (chat_id,))


class _FernetCipher:
    def encrypt(self, plaintext: bytes) -> tuple[str, bytes]:
        return "fernet", get_fernet().encrypt(plaintext)

    def decrypt(self, ciphername: str, ciphertext: bytes) -> bytes:
        if ciphername != "fernet":
            raise ValueError("Cifrado de checkpoint desconocido.")
        return get_fernet().decrypt(ciphertext)


def checkpoint_serializer() -> EncryptedSerializer:
    get_fernet()
    return EncryptedSerializer(_FernetCipher(), JsonPlusSerializer(allowed_msgpack_modules=None))

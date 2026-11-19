from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.config import settings
from app.ingestion.chunk import Chunk, chunk_pages
from app.ingestion.embed import embed_texts

VALID_CATEGORIES = {"normative", "nutrition", "corporate", "guide"}
VALID_EXTRACTION_STATUS = {"pending", "processing", "complete", "partial", "failed"}

EmbedFn = Callable[[Sequence[str]], list[list[float]]]


class IngestionError(RuntimeError):
    pass


@dataclass(slots=True)
class IngestionResult:
    document_id: str
    version_id: str
    chunks: int
    embeddings: int
    pages: int
    ocr_pages: int
    chars: int
    skipped: bool = False


def load_manifest(path: Path) -> dict[str, dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    documents = payload.get("documents", [])
    result: dict[str, dict] = {}
    for document in documents:
        document_id = document.get("id")
        if not document_id:
            raise IngestionError("El manifiesto contiene un documento sin id.")
        if document_id in result:
            raise IngestionError(f"Id duplicado en el manifiesto: {document_id}.")
        result[document_id] = document
    return result


def load_extraction(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def merge_manifest(record: Mapping[str, Any], manifest_doc: Mapping[str, Any]) -> dict:
    document_id = record.get("id") or manifest_doc.get("id")
    title = record.get("title") or manifest_doc.get("title")
    category = record.get("category") or manifest_doc.get("category")
    sha256 = record.get("sha256")

    if not document_id:
        raise IngestionError("El documento no tiene id.")
    if not title:
        raise IngestionError(f"{document_id}: falta el título.")
    if category not in VALID_CATEGORIES:
        raise IngestionError(f"{document_id}: categoría inválida {category!r}.")
    if not sha256:
        raise IngestionError(f"{document_id}: falta el SHA-256.")

    return {
        "id": str(document_id),
        "title": str(title),
        "category": str(category),
        "doc_type": record.get("doc_type") or manifest_doc.get("doc_type"),
        "country": record.get("country") or manifest_doc.get("country") or "CO",
        "language": record.get("language") or manifest_doc.get("language") or "es",
        "vigente": bool(
            record.get("vigente")
            if record.get("vigente") is not None
            else manifest_doc.get("vigente", True)
        ),
        "version": str(record.get("version") or manifest_doc.get("version") or "sin-version"),
        "sha256": str(sha256),
        "filename": record.get("filename") or manifest_doc.get("filename") or "",
        "page_count": int(record.get("page_count") or 0),
        "effective_date": manifest_doc.get("effective_date"),
        "published_date": manifest_doc.get("published_date"),
        "source_page": manifest_doc.get("source_page"),
        "pdf_url": manifest_doc.get("pdf_url"),
        "notes": manifest_doc.get("notes"),
        "extraction_status": record.get("status") or "pending",
        "extracted_at": record.get("extracted_at"),
        "ocr_model": record.get("ocr_model"),
        "stats": dict(record.get("stats") or {}),
        "errors": list(record.get("errors") or []),
        "pages": list(record.get("pages") or []),
    }


def build_chunks(
    record: Mapping[str, Any],
    *,
    max_chars: int = settings.chunk_max_chars,
    overlap_chars: int = settings.chunk_overlap_chars,
    min_chars: int = settings.chunk_min_chars,
) -> list[Chunk]:
    return chunk_pages(
        record.get("pages") or [],
        max_chars=max_chars,
        overlap_chars=overlap_chars,
        min_chars=min_chars,
    )


def _document_metadata(document: dict) -> Jsonb:
    return Jsonb(
        {
            "source_page": document["source_page"],
            "pdf_url": document["pdf_url"],
            "notes": document["notes"],
            "errors": document["errors"],
            "ocr_model": document["ocr_model"],
        }
    )


def _fetch_version(cur, document_id: str, version: str) -> dict | None:
    cur.execute(
        """
        select id, sha256, is_current
        from public.document_versions
        where document_id = %s and version = %s
        """,
        (document_id, version),
    )
    return cur.fetchone()


def _count_chunks(cur, version_id: Any) -> int:
    cur.execute(
        "select count(*) as count from public.chunks where version_id = %s",
        (version_id,),
    )
    row = cur.fetchone()
    return int(row["count"]) if row else 0


def _count_model_embeddings(cur, version_id: Any, model: str) -> int:
    cur.execute(
        """
        select count(ce.id) as count
        from public.chunks c
        join public.chunk_embeddings ce on ce.chunk_id = c.id
        where c.version_id = %s and ce.model = %s
        """,
        (version_id, model),
    )
    row = cur.fetchone()
    return int(row["count"]) if row else 0


def _ensure_document(cur, document: dict) -> None:
    cur.execute(
        """
        insert into public.documents
            (id, title, category, doc_type, country, language, vigente, source_url)
        values (%s, %s, %s, %s, %s, %s, %s, %s)
        on conflict (id) do update set
            title = excluded.title,
            category = excluded.category,
            doc_type = excluded.doc_type,
            country = excluded.country,
            language = excluded.language,
            vigente = excluded.vigente,
            source_url = excluded.source_url
        """,
        (
            document["id"],
            document["title"],
            document["category"],
            document["doc_type"],
            document["country"],
            document["language"],
            document["vigente"],
            document["source_page"] or document["pdf_url"],
        ),
    )


def ensure_document(
    conn: psycopg.Connection,
    record: Mapping[str, Any],
    manifest_doc: Mapping[str, Any],
) -> dict:
    """Crea o actualiza el documento antes de registrar ingestion_runs."""
    document = merge_manifest(record, manifest_doc)
    with conn.transaction():
        with conn.cursor() as cur:
            _ensure_document(cur, document)
    return document


def _ensure_version(cur, document: dict) -> str:
    existing = _fetch_version(cur, document["id"], document["version"])
    extraction_status = (
        document["extraction_status"]
        if document["extraction_status"] in VALID_EXTRACTION_STATUS
        else "pending"
    )
    version_values = (
        document["sha256"],
        document["filename"],
        document["page_count"],
        _parse_date(document["effective_date"]),
        _parse_date(document["published_date"]),
        document["vigente"],
        document["pdf_url"] or document["source_page"],
        extraction_status,
        _parse_datetime(document["extracted_at"]),
        document["ocr_model"],
        Jsonb(document["stats"]),
        _document_metadata(document),
    )

    if existing:
        version_id = existing["id"]
        cur.execute(
            """
            select id from public.document_versions
            where sha256 = %s and id <> %s
            """,
            (document["sha256"], version_id),
        )
        if cur.fetchone():
            raise IngestionError(
                f"{document['id']}: el SHA-256 ya pertenece a otra versión."
            )

        cur.execute(
            """
            update public.document_versions
            set is_current = false
            where document_id = %s and is_current and id <> %s
            """,
            (document["id"], version_id),
        )
        cur.execute(
            """
            update public.document_versions set
                sha256 = %s,
                filename = %s,
                page_count = %s,
                effective_date = %s,
                published_date = %s,
                vigente = %s,
                is_current = true,
                source_url = %s,
                extraction_status = %s,
                extracted_at = %s,
                ocr_model = %s,
                extraction_stats = %s,
                metadata = %s
            where id = %s
            returning id
            """,
            (*version_values, version_id),
        )
        row = cur.fetchone()
        if not row:
            raise IngestionError(f"{document['id']}: no se pudo actualizar la versión.")
        return str(row["id"])

    cur.execute(
        "select id from public.document_versions where sha256 = %s",
        (document["sha256"],),
    )
    if cur.fetchone():
        raise IngestionError(
            f"{document['id']}: el SHA-256 ya pertenece a otro documento."
        )

    cur.execute(
        """
        update public.document_versions
        set is_current = false
        where document_id = %s and is_current
        """,
        (document["id"],),
    )
    cur.execute(
        """
        insert into public.document_versions (
            document_id, version, sha256, filename, page_count,
            effective_date, published_date, vigente, is_current,
            source_url, extraction_status, extracted_at, ocr_model,
            extraction_stats, metadata
        )
        values (
            %s, %s, %s, %s, %s,
            %s, %s, %s, true,
            %s, %s, %s, %s,
            %s, %s
        )
        returning id
        """,
        (
            document["id"],
            document["version"],
            *version_values,
        ),
    )
    row = cur.fetchone()
    if not row:
        raise IngestionError(f"{document['id']}: no se pudo insertar la versión.")
    return str(row["id"])


def _replace_chunks(
    cur,
    document: dict,
    version_id: str,
    chunks: Sequence[Chunk],
    vectors: Sequence[Sequence[float]],
) -> None:
    cur.execute("delete from public.chunks where version_id = %s", (version_id,))
    if not chunks:
        return

    chunk_rows = [
        (
            document["id"],
            version_id,
            chunk.index,
            chunk.page_start,
            chunk.page_end,
            chunk.section,
            chunk.content,
            chunk.token_count,
            Jsonb({"page": chunk.page_start, "section": chunk.section}),
        )
        for chunk in chunks
    ]
    cur.executemany(
        """
        insert into public.chunks (
            document_id, version_id, chunk_index, page_start, page_end,
            section, content, token_count, metadata
        )
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        chunk_rows,
    )

    cur.execute(
        """
        select id, chunk_index
        from public.chunks
        where version_id = %s
        order by chunk_index
        """,
        (version_id,),
    )
    ids_by_index = {row["chunk_index"]: row["id"] for row in cur.fetchall()}
    if len(ids_by_index) != len(chunks):
        raise IngestionError(
            f"{document['id']}: se esperaban {len(chunks)} chunks y se encontraron "
            f"{len(ids_by_index)}."
        )

    embedding_rows = []
    for chunk, vector in zip(chunks, vectors, strict=True):
        chunk_id = ids_by_index.get(chunk.index)
        if chunk_id is None:
            raise IngestionError(
                f"{document['id']}: falta el chunk con índice {chunk.index}."
            )
        embedding_rows.append(
            (chunk_id, settings.cohere_embed_model, len(vector), list(vector))
        )

    cur.executemany(
        """
        insert into public.chunk_embeddings (chunk_id, model, dimension, embedding)
        values (%s, %s, %s, %s)
        """,
        embedding_rows,
    )


def ingest_document(
    conn: psycopg.Connection,
    record: Mapping[str, Any],
    manifest_doc: Mapping[str, Any],
    *,
    force: bool = False,
    embed_fn: EmbedFn = embed_texts,
    max_chars: int = settings.chunk_max_chars,
    overlap_chars: int = settings.chunk_overlap_chars,
    min_chars: int = settings.chunk_min_chars,
) -> IngestionResult:
    document = merge_manifest(record, manifest_doc)
    chunks = build_chunks(
        record,
        max_chars=max_chars,
        overlap_chars=overlap_chars,
        min_chars=min_chars,
    )
    if not chunks:
        raise IngestionError(
            f"{document['id']}: no hay texto suficiente para generar chunks."
        )

    with conn.cursor(row_factory=dict_row) as cur:
        existing = _fetch_version(cur, document["id"], document["version"])
        existing_chunks = _count_chunks(cur, existing["id"]) if existing else 0
        existing_embeddings = (
            _count_model_embeddings(cur, existing["id"], settings.cohere_embed_model)
            if existing
            else 0
        )
    if not conn.autocommit:
        conn.commit()

    if (
        existing
        and existing["sha256"] == document["sha256"]
        and existing_chunks > 0
        and existing_embeddings == existing_chunks
        and not force
    ):
        if existing["is_current"]:
            return IngestionResult(
                document_id=document["id"],
                version_id=str(existing["id"]),
                chunks=0,
                embeddings=0,
                pages=document["page_count"],
                ocr_pages=int(document["stats"].get("ocr_pages", 0)),
                chars=int(document["stats"].get("total_chars", 0)),
                skipped=True,
            )

        with conn.transaction():
            with conn.cursor(row_factory=dict_row) as cur:
                _ensure_document(cur, document)
                _ensure_version(cur, document)
        return IngestionResult(
            document_id=document["id"],
            version_id=str(existing["id"]),
            chunks=0,
            embeddings=0,
            pages=document["page_count"],
            ocr_pages=int(document["stats"].get("ocr_pages", 0)),
            chars=int(document["stats"].get("total_chars", 0)),
            skipped=True,
        )

    vectors = embed_fn([chunk.content for chunk in chunks])
    if len(vectors) != len(chunks):
        raise IngestionError(
            f"{document['id']}: Cohere devolvió {len(vectors)} embeddings para "
            f"{len(chunks)} chunks."
        )
    if any(len(vector) != settings.cohere_embed_dim for vector in vectors):
        raise IngestionError(
            f"{document['id']}: dimensión de embedding distinta de "
            f"{settings.cohere_embed_dim}."
        )

    with conn.transaction():
        with conn.cursor(row_factory=dict_row) as cur:
            _ensure_document(cur, document)
            version_id = _ensure_version(cur, document)
            _replace_chunks(cur, document, version_id, chunks, vectors)

    return IngestionResult(
        document_id=document["id"],
        version_id=version_id,
        chunks=len(chunks),
        embeddings=len(vectors),
        pages=document["page_count"],
        ocr_pages=int(document["stats"].get("ocr_pages", 0)),
        chars=int(document["stats"].get("total_chars", 0)),
        skipped=False,
    )

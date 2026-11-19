-- Esquema inicial del Agente Alpina.
-- Aplicar con Supabase MCP (apply_migration) o psql.
-- pgvector se instala en public; el tipo vector queda disponible por search_path.

do $$ begin
    create schema if not exists extensions;
exception when others then null;
end $$;

do $$ begin
    create extension if not exists vector with schema extensions;
exception when others then null;
end $$;

do $$ begin
    create extension if not exists pgcrypto with schema extensions;
exception when others then null;
end $$;

create or replace function public.set_updated_at()
returns trigger
language plpgsql
set search_path = pg_catalog, public
as $$
begin
    new.updated_at = pg_catalog.now();
    return new;
end;
$$;

create table if not exists public.documents (
    id text primary key,
    title text not null,
    category text not null check (category in ('normative', 'nutrition', 'corporate', 'guide')),
    doc_type text,
    country text not null default 'CO',
    language text not null default 'es',
    vigente boolean not null default true,
    source_url text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.document_versions (
    id uuid primary key default gen_random_uuid(),
    document_id text not null references public.documents(id) on delete cascade,
    version text not null default 'sin-version',
    sha256 text not null unique,
    filename text not null,
    page_count integer not null default 0 check (page_count >= 0),
    effective_date date,
    published_date date,
    vigente boolean not null default true,
    is_current boolean not null default true,
    source_url text,
    storage_key text,
    extraction_status text not null default 'pending'
        check (extraction_status in ('pending', 'processing', 'complete', 'partial', 'failed')),
    extracted_at timestamptz,
    ocr_model text,
    extraction_stats jsonb not null default '{}'::jsonb,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (document_id, version)
);

create unique index if not exists document_versions_one_current_idx
    on public.document_versions (document_id)
    where is_current;

create index if not exists document_versions_document_id_idx
    on public.document_versions (document_id);

create table if not exists public.chunks (
    id uuid primary key default gen_random_uuid(),
    document_id text not null references public.documents(id) on delete cascade,
    version_id uuid not null references public.document_versions(id) on delete cascade,
    chunk_index integer not null check (chunk_index >= 0),
    page_start integer not null check (page_start >= 1),
    page_end integer not null check (page_end >= page_start),
    section text,
    content text not null,
    token_count integer check (token_count is null or token_count > 0),
    content_tsv tsvector generated always as (to_tsvector('spanish'::regconfig, content)) stored,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    unique (version_id, chunk_index)
);

create index if not exists chunks_document_id_idx on public.chunks (document_id);
create index if not exists chunks_version_id_idx on public.chunks (version_id);
create index if not exists chunks_content_tsv_idx on public.chunks using gin (content_tsv);

create table if not exists public.chunk_embeddings (
    id bigserial primary key,
    chunk_id uuid not null references public.chunks(id) on delete cascade,
    model text not null,
    dimension integer not null check (dimension > 0),
    embedding vector(1024) not null,
    created_at timestamptz not null default now(),
    unique (chunk_id, model)
);

create index if not exists chunk_embeddings_hnsw_idx
    on public.chunk_embeddings using hnsw (embedding vector_cosine_ops);
create index if not exists chunk_embeddings_chunk_id_idx
    on public.chunk_embeddings (chunk_id);

create table if not exists public.chats (
    id uuid primary key default gen_random_uuid(),
    session_id text,
    user_id text,
    title text,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table public.chats
    add column if not exists session_id text,
    add column if not exists user_id text;

create index if not exists chats_session_id_idx on public.chats (session_id);
create index if not exists chats_user_id_idx on public.chats (user_id);

create table if not exists public.messages (
    id uuid primary key default gen_random_uuid(),
    chat_id uuid not null references public.chats(id) on delete cascade,
    role text not null check (role in ('system', 'user', 'assistant', 'tool')),
    content text not null,
    citations jsonb not null default '[]'::jsonb,
    model text,
    token_usage jsonb not null default '{}'::jsonb,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists messages_chat_id_created_at_idx
    on public.messages (chat_id, created_at);

create table if not exists public.ingestion_runs (
    id uuid primary key default gen_random_uuid(),
    document_id text references public.documents(id) on delete cascade,
    version_id uuid references public.document_versions(id) on delete cascade,
    status text not null default 'pending'
        check (status in ('pending', 'running', 'complete', 'partial', 'failed')),
    pages_total integer not null default 0,
    pages_ocr integer not null default 0,
    pages_failed integer not null default 0,
    error text,
    metadata jsonb not null default '{}'::jsonb,
    started_at timestamptz,
    finished_at timestamptz,
    created_at timestamptz not null default now()
);

create index if not exists ingestion_runs_document_id_idx
    on public.ingestion_runs (document_id);

create table if not exists public.reports (
    id uuid primary key default gen_random_uuid(),
    chat_id uuid references public.chats(id) on delete set null,
    session_id text,
    report_type text not null check (report_type in ('pdf', 'xlsx', 'docx')),
    title text not null,
    status text not null default 'pending'
        check (status in ('pending', 'approved', 'generated', 'failed', 'revoked')),
    spec jsonb not null default '{}'::jsonb,
    storage_key text,
    error text,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table public.reports
    add column if not exists session_id text;

create index if not exists reports_chat_id_idx on public.reports (chat_id);
create index if not exists reports_session_id_idx on public.reports (session_id);

create table if not exists public.audit_events (
    id bigserial primary key,
    chat_id uuid references public.chats(id) on delete set null,
    message_id uuid references public.messages(id) on delete set null,
    event_type text not null,
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists audit_events_chat_id_created_at_idx
    on public.audit_events (chat_id, created_at);

create or replace trigger documents_set_updated_at
    before update on public.documents
    for each row execute function public.set_updated_at();

create or replace trigger document_versions_set_updated_at
    before update on public.document_versions
    for each row execute function public.set_updated_at();

create or replace trigger chats_set_updated_at
    before update on public.chats
    for each row execute function public.set_updated_at();

create or replace trigger reports_set_updated_at
    before update on public.reports
    for each row execute function public.set_updated_at();

alter table public.documents enable row level security;
alter table public.document_versions enable row level security;
alter table public.chunks enable row level security;
alter table public.chunk_embeddings enable row level security;
alter table public.chats enable row level security;
alter table public.messages enable row level security;
alter table public.ingestion_runs enable row level security;
alter table public.reports enable row level security;
alter table public.audit_events enable row level security;

-- Catálogo estructurado de productos oficiales.
create table if not exists public.products (
    id text primary key,
    ean text unique,
    name text not null,
    brand text not null default 'Alpina',
    presentation text,
    price numeric(12, 2),
    currency text not null default 'COP',
    protein_g numeric(8, 2),
    claims jsonb not null default '[]'::jsonb,
    ingredients text,
    allergens text,
    availability text,
    source_url text not null,
    source_page integer not null default 1,
    verified_at timestamptz not null default now(),
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table public.products
    add column if not exists search_tsv tsvector
    generated always as (
        to_tsvector(
            'spanish'::regconfig,
            coalesce(name, '') || ' ' || coalesce(ean, '') || ' ' || coalesce(presentation, '')
        )
    ) stored;

create index if not exists products_search_tsv_idx
    on public.products using gin (search_tsv);

create or replace trigger products_set_updated_at
    before update on public.products
    for each row execute function public.set_updated_at();

alter table public.products enable row level security;

drop policy if exists alpina_app_all on public.products;
create policy alpina_app_all on public.products
    for all to alpina_app using (true) with check (true);

grant select, insert, update, delete on public.products to alpina_app;

-- Endurecimiento posterior al esquema inicial.
-- pgvector se mueve al esquema extensions (recomendación de Supabase).
create schema if not exists extensions;
do $$ begin
    alter extension vector set schema extensions;
exception when others then null;
end $$;

-- search_path fijo para evitar resolución dinámica de funciones.
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

-- La función de auto-RLS de Supabase no debe ser invocable por la API pública si existe.
do $$ begin
    revoke execute on function public.rls_auto_enable() from public;
exception when others then null;
end $$;

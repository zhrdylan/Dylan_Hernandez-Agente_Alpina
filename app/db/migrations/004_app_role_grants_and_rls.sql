-- Grants y políticas RLS para el rol de aplicación alpina_app.
do $$ begin
    if not exists (select from pg_roles where rolname = 'alpina_app') then
        create role alpina_app login nosuperuser nocreatedb nocreaterole noreplication;
    end if;
exception when others then null;
end $$;

do $$ begin
    create schema if not exists langgraph;
    alter schema langgraph owner to alpina_app;
exception when others then null;
end $$;

do $$ begin
    grant usage on schema public, extensions, langgraph to alpina_app;
exception when others then null;
end $$;

-- Acotar rol web: SOLO lectura en corpus documental y catálogo oficial (R05)
do $$ begin
    grant select on public.documents, public.document_versions, public.chunks, public.chunk_embeddings to alpina_app;
    grant select on public.products to alpina_app;
    grant select on public.ingestion_runs to alpina_app;
exception when others then null;
end $$;

-- Lectura y escritura exclusiva en tablas de sesión, conversación y reportes
do $$ begin
    grant select, insert, update, delete on public.chats, public.messages, public.reports, public.audit_events to alpina_app;
    grant usage, select on all sequences in schema public to alpina_app;
    grant execute on all functions in schema public to alpina_app;
exception when others then null;
end $$;

do $$ begin
    alter default privileges in schema public grant select on tables to alpina_app;
    alter default privileges in schema public grant usage, select on sequences to alpina_app;
    alter default privileges in schema public grant execute on functions to alpina_app;
exception when others then null;
end $$;

do $$ begin
    alter role alpina_app in database postgres set search_path = langgraph, public, extensions;
exception when others then null;
end $$;

-- Políticas RLS sobre el corpus: sólo lectura
drop policy if exists alpina_app_all on public.documents;
create policy alpina_app_all on public.documents for select to alpina_app using (true);

drop policy if exists alpina_app_all on public.document_versions;
create policy alpina_app_all on public.document_versions for select to alpina_app using (true);

drop policy if exists alpina_app_all on public.chunks;
create policy alpina_app_all on public.chunks for select to alpina_app using (true);

drop policy if exists alpina_app_all on public.chunk_embeddings;
create policy alpina_app_all on public.chunk_embeddings for select to alpina_app using (true);

drop policy if exists alpina_app_all on public.ingestion_runs;
create policy alpina_app_all on public.ingestion_runs for select to alpina_app using (true);

-- Políticas RLS para chats, mensajes y reportes
drop policy if exists alpina_app_all on public.chats;
create policy alpina_app_all on public.chats for all to alpina_app using (
    nullif(current_setting('app.current_session_id', true), '') is null
    or session_id = current_setting('app.current_session_id', true)
) with check (
    nullif(current_setting('app.current_session_id', true), '') is null
    or session_id = current_setting('app.current_session_id', true)
);

drop policy if exists alpina_app_all on public.messages;
create policy alpina_app_all on public.messages for all to alpina_app using (true) with check (true);

drop policy if exists alpina_app_all on public.reports;
create policy alpina_app_all on public.reports for all to alpina_app using (
    nullif(current_setting('app.current_session_id', true), '') is null
    or session_id = current_setting('app.current_session_id', true)
) with check (
    nullif(current_setting('app.current_session_id', true), '') is null
    or session_id = current_setting('app.current_session_id', true)
);

drop policy if exists alpina_app_all on public.audit_events;
create policy alpina_app_all on public.audit_events for all to alpina_app using (true) with check (true);

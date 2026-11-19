-- Grants y políticas RLS para el rol de aplicación alpina_app.
-- El rol se crea una sola vez fuera de esta migración, con un verificador SCRAM,
-- para no almacenar contraseñas en el historial de migraciones.
--
-- Bootstrap:
--   create role alpina_app login password '<SCRAM-SHA-256$...>'
--     nosuperuser nocreatedb nocreaterole noreplication nobypassrls;
--   grant alpina_app to postgres;  -- permite otorgar privilegios y defaults

create schema if not exists langgraph;
alter schema langgraph owner to alpina_app;

grant usage on schema public, extensions, langgraph to alpina_app;
grant select, insert, update, delete on all tables in schema public to alpina_app;
grant usage, select on all sequences in schema public to alpina_app;
grant execute on all functions in schema public to alpina_app;

alter default privileges in schema public grant select, insert, update, delete on tables to alpina_app;
alter default privileges in schema public grant usage, select on sequences to alpina_app;
alter default privileges in schema public grant execute on functions to alpina_app;

alter role alpina_app in database postgres set search_path = langgraph, public, extensions;

drop policy if exists alpina_app_all on public.documents;
create policy alpina_app_all on public.documents for all to alpina_app using (true) with check (true);

drop policy if exists alpina_app_all on public.document_versions;
create policy alpina_app_all on public.document_versions for all to alpina_app using (true) with check (true);

drop policy if exists alpina_app_all on public.chunks;
create policy alpina_app_all on public.chunks for all to alpina_app using (true) with check (true);

drop policy if exists alpina_app_all on public.chunk_embeddings;
create policy alpina_app_all on public.chunk_embeddings for all to alpina_app using (true) with check (true);

drop policy if exists alpina_app_all on public.chats;
create policy alpina_app_all on public.chats for all to alpina_app using (true) with check (true);

drop policy if exists alpina_app_all on public.messages;
create policy alpina_app_all on public.messages for all to alpina_app using (true) with check (true);

drop policy if exists alpina_app_all on public.ingestion_runs;
create policy alpina_app_all on public.ingestion_runs for all to alpina_app using (true) with check (true);

drop policy if exists alpina_app_all on public.reports;
create policy alpina_app_all on public.reports for all to alpina_app using (true) with check (true);

drop policy if exists alpina_app_all on public.audit_events;
create policy alpina_app_all on public.audit_events for all to alpina_app using (true) with check (true);

-- El rol migrador debe ser propietario de las tablas de public.
do $$ begin
    if not exists (select 1 from pg_roles where rolname = 'alpina_app' and not rolsuper) then
        raise exception 'Se requiere el rol alpina_app sin privilegios de superusuario';
    end if;
    if exists (select 1 from pg_roles where rolname = 'alpina_app' and rolbypassrls) then
        alter role alpina_app nobypassrls;
    end if;
end $$;

-- 004 puede ejecutarse antes de que exista el catálogo de productos.
grant select on public.documents, public.document_versions, public.chunks,
    public.chunk_embeddings, public.ingestion_runs to alpina_app;

-- Los informes heredados de un chat adoptan el propietario de ese chat.
update public.reports as report
set session_id = chat.session_id
from public.chats as chat
where report.session_id is null and chat.id = report.chat_id
  and nullif(chat.session_id, '') is not null;

-- La política restrictiva también se aplica si la plataforma añade otros permisos.
do $$
declare
    relation text;
begin
    foreach relation in array array['chats', 'messages', 'reports', 'audit_events'] loop
        execute format('alter table public.%I enable row level security', relation);
        execute format('alter table public.%I force row level security', relation);
        execute format('drop policy if exists alpina_app_all on public.%I', relation);
        execute format('create policy alpina_app_all on public.%I for all to alpina_app using (true)', relation);
    end loop;
end $$;

create policy alpina_owner_scope on public.chats as restrictive for all to public
using (session_id = nullif(current_setting('app.current_session_id', true), ''));

create policy alpina_owner_scope on public.messages as restrictive for all to public
using (exists (select from public.chats where id = messages.chat_id));

create policy alpina_owner_scope on public.reports as restrictive for all to public
using (session_id = nullif(current_setting('app.current_session_id', true), ''))
with check (
    session_id = nullif(current_setting('app.current_session_id', true), '')
    and (chat_id is null or exists (select from public.chats where id = reports.chat_id))
);

create policy alpina_owner_scope on public.audit_events as restrictive for all to public
using (exists (select from public.chats where id = audit_events.chat_id))
with check (
    exists (select from public.chats where id = audit_events.chat_id)
    and (message_id is null or exists (
        select from public.messages where id = audit_events.message_id and chat_id = audit_events.chat_id
    ))
);

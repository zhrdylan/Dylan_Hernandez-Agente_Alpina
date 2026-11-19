-- Migración 007: Sesión y propiedad en chats/reports y soporte oficial docx
alter table public.chats
    add column if not exists session_id text,
    add column if not exists user_id text;

create index if not exists chats_session_id_idx on public.chats (session_id);
create index if not exists chats_user_id_idx on public.chats (user_id);

alter table public.reports
    add column if not exists session_id text;

create index if not exists reports_session_id_idx on public.reports (session_id);

alter table public.reports drop constraint if exists reports_report_type_check;
alter table public.reports add constraint reports_report_type_check
    check (report_type in ('pdf', 'xlsx', 'docx'));

alter table public.reports drop constraint if exists reports_status_check;
alter table public.reports add constraint reports_status_check
    check (status in ('pending', 'approved', 'generated', 'failed', 'revoked'));

-- Índices de cobertura para las foreign keys detectadas por el advisor.
create index if not exists audit_events_message_id_idx
    on public.audit_events (message_id);

create index if not exists ingestion_runs_version_id_idx
    on public.ingestion_runs (version_id);

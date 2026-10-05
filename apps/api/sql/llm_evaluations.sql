-- Per-user cache of LLM job evaluations, keyed by resume version (profiles.content_hash).
-- Reruns only call Groq for jobs without a row here. Purged by the API when a resume is
-- deleted or replaced; ON DELETE CASCADE also covers account deletion.
-- The API connects with DATABASE_URL (postgres role, bypasses RLS); RLS with no policies blocks
-- direct anon/authenticated access from clients.

create table if not exists public.llm_evaluations (
    user_id      uuid        not null references auth.users (id) on delete cascade,
    content_hash text        not null,
    job_id       text        not null,
    job_sig      text        not null,
    evaluation   jsonb       not null,
    created_at   timestamptz not null default now(),
    primary key (user_id, content_hash, job_id)
);

create index if not exists llm_evaluations_user_idx on public.llm_evaluations (user_id);

alter table public.llm_evaluations enable row level security;

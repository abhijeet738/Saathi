-- Saathi schema v1. Run ONCE, on a fresh database:
--   make migrate            (or paste into the Supabase SQL editor)
-- It runs as a single transaction: if anything fails, nothing is applied and you can fix and re-run.
-- Never edit this file after it has been applied. Later changes go in 002_*.sql, 003_*.sql ...

begin;

create extension if not exists vector;

-- People and how they reach Saathi -------------------------------------------
create table users (
    id           uuid primary key default gen_random_uuid(),
    display_name text not null,
    timezone     text not null default 'Asia/Kolkata',
    -- short context used for email triage, e.g. "Final-year B.Tech CSE student"
    about        text not null default '',
    is_active    boolean not null default true,
    created_at   timestamptz not null default now()
);

-- The allowlist: messages from unknown senders are ignored.
create table channel_identities (
    id              uuid primary key default gen_random_uuid(),
    user_id         uuid not null references users(id) on delete cascade,
    channel         text not null check (channel in ('telegram', 'whatsapp', 'test')),
    -- Telegram from.id / WhatsApp phone number (wa_id)
    channel_user_id text not null,
    -- where replies go
    chat_id         text not null,
    unique (channel, channel_user_id)
);

create table user_settings (
    user_id           uuid primary key references users(id) on delete cascade,
    -- used for proactive messages (reminders, brief, alerts)
    preferred_channel text not null default 'telegram'
                      check (preferred_channel in ('telegram', 'whatsapp', 'test')),
    brief_time        time not null default '08:00',
    quiet_start       time not null default '23:00',
    quiet_end         time not null default '07:00',
    skills_enabled    jsonb not null default
                      '{"inbox": true, "planner": true, "brain": true, "money": true, "brief": true}'
);

-- Conversation log (also used to drop duplicate webhook retries) -------------
create table messages (
    id                 bigserial primary key,
    user_id            uuid references users(id) on delete set null,
    channel            text not null,
    direction          text not null check (direction in ('in', 'out')),
    -- Must be unique per channel. Telegram message ids repeat across chats, so store
    -- '<chat_id>:<message_id>' for Telegram; callbacks use 'cb_<callback id>'.
    channel_message_id text,
    -- text | voice | image | document | callback
    type               text not null,
    content            text,
    meta               jsonb not null default '{}',
    created_at         timestamptz not null default now(),
    unique (channel, direction, channel_message_id)
);
create index messages_user_time on messages (user_id, created_at desc);

-- Planner -------------------------------------------------------------------
create table reminders (
    id                uuid primary key default gen_random_uuid(),
    user_id           uuid not null references users(id) on delete cascade,
    text              text not null,
    due_at            timestamptz not null,
    recurrence        text check (recurrence in ('daily', 'weekly', 'monthly')),
    -- 'sending' = claimed by the dispatcher; if still 'sending' after 5 minutes the
    -- dispatcher reclaims it, so a crash causes a rare duplicate instead of a lost reminder.
    status            text not null default 'scheduled'
                      check (status in ('scheduled', 'sending', 'sent', 'cancelled', 'failed')),
    calendar_event_id text,
    created_at        timestamptz not null default now(),
    claimed_at        timestamptz,
    sent_at           timestamptz
);
create index reminders_due on reminders (status, due_at);

-- Second brain (RAG) --------------------------------------------------------
create table documents (
    id          uuid primary key default gen_random_uuid(),
    user_id     uuid not null references users(id) on delete cascade,
    title       text not null,
    source_type text not null check (source_type in ('note', 'link', 'pdf', 'image')),
    -- URL or file name
    source_ref  text,
    summary     text,
    tags        text[] not null default '{}',
    created_at  timestamptz not null default now()
);

create table doc_chunks (
    id          bigserial primary key,
    document_id uuid not null references documents(id) on delete cascade,
    user_id     uuid not null references users(id) on delete cascade,
    chunk_index int not null,
    content     text not null,
    embedding   vector(768) not null
);
create index doc_chunks_embedding on doc_chunks using hnsw (embedding vector_cosine_ops);
create index doc_chunks_user on doc_chunks (user_id);
create index doc_chunks_document on doc_chunks (document_id);

-- Long-term memory ----------------------------------------------------------
create table memories (
    id         uuid primary key default gen_random_uuid(),
    user_id    uuid not null references users(id) on delete cascade,
    fact       text not null,
    category   text not null default 'general',
    embedding  vector(768) not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create index memories_embedding on memories using hnsw (embedding vector_cosine_ops);
create index memories_user on memories (user_id);

-- Money ---------------------------------------------------------------------
create table expenses (
    id         uuid primary key default gen_random_uuid(),
    user_id    uuid not null references users(id) on delete cascade,
    amount     numeric(12, 2) not null check (amount > 0),
    currency   text not null default 'INR',
    category   text not null,
    merchant   text,
    note       text,
    spent_at   timestamptz not null default now(),
    source     text not null check (source in ('text', 'voice', 'receipt', 'bank_email', 'manual')),
    -- Gmail id / Telegram message id. NULL for plain typed entries (never de-duplicated).
    source_ref text,
    created_at timestamptz not null default now(),
    -- the same bank email can never be logged twice
    unique (user_id, source, source_ref)
);
create index expenses_user_time on expenses (user_id, spent_at desc);

create table budgets (
    user_id       uuid not null references users(id) on delete cascade,
    category      text not null,
    monthly_limit numeric(12, 2) not null check (monthly_limit > 0),
    primary key (user_id, category)
);

-- Inbox ---------------------------------------------------------------------
-- A row is created when an email is first seen, and marked processed only after it was
-- classified and every follow-up (alert, expense) succeeded. Rows that are not processed
-- yet are retried on the next run (up to 3 attempts), so a mid-run failure never loses an email.
create table email_items (
    gmail_id     text primary key,
    user_id      uuid not null references users(id) on delete cascade,
    thread_id    text,
    from_addr    text,
    subject      text,
    priority     text check (priority in ('urgent', 'normal', 'low', 'bank_alert')),
    summary      text,
    notified     boolean not null default false,
    received_at  timestamptz,
    seen_at      timestamptz not null default now(),
    processed    boolean not null default false,
    processed_at timestamptz,
    attempts     int not null default 0
);
create index email_items_retry on email_items (user_id, processed) where not processed;
create index email_items_seen on email_items (seen_at desc);

-- Human-in-the-loop confirmations -------------------------------------------
create table pending_actions (
    id          uuid primary key default gen_random_uuid(),
    user_id     uuid not null references users(id) on delete cascade,
    action_type text not null check (action_type in
                ('send_email', 'delete_reminder', 'delete_document', 'forget_memory', 'delete_event')),
    payload     jsonb not null,
    -- exactly what the user sees before confirming
    preview     text not null,
    status      text not null default 'pending'
                check (status in ('pending', 'prompted', 'confirmed', 'cancelled', 'expired', 'failed')),
    created_at  timestamptz not null default now(),
    expires_at  timestamptz not null default now() + interval '30 minutes',
    resolved_at timestamptz
);
create index pending_open on pending_actions (user_id, status);

-- Observability -------------------------------------------------------------
create table event_log (
    id         bigserial primary key,
    level      text not null check (level in ('info', 'warn', 'error')),
    -- workflow or service name
    source     text not null,
    user_id    uuid,
    message    text not null,
    data       jsonb not null default '{}',
    created_at timestamptz not null default now()
);
create index event_log_time on event_log (created_at desc);

-- Security: row level security on EVERY table ---------------------------------
-- Supabase exposes the public schema through a REST "Data API". With RLS on and no
-- policies, that API can read and write nothing. The API and n8n connect as the
-- `postgres` role, which bypasses RLS, so Saathi itself is unaffected.
alter table users               enable row level security;
alter table channel_identities  enable row level security;
alter table user_settings       enable row level security;
alter table messages            enable row level security;
alter table reminders           enable row level security;
alter table documents           enable row level security;
alter table doc_chunks          enable row level security;
alter table memories            enable row level security;
alter table expenses            enable row level security;
alter table budgets             enable row level security;
alter table email_items         enable row level security;
alter table pending_actions     enable row level security;
alter table event_log           enable row level security;

-- Belt and braces: also remove the Data API roles' table privileges (Supabase only;
-- skipped on a plain Postgres where these roles do not exist).
do $$
begin
    if exists (select 1 from pg_roles where rolname = 'anon') then
        revoke all on all tables in schema public from anon, authenticated;
        revoke all on all sequences in schema public from anon, authenticated;
    end if;
end
$$;

commit;

-- Check afterwards (run by hand):
--   select count(*) from information_schema.tables
--    where table_schema = 'public' and table_type = 'BASE TABLE';          -- expect 13
--   select relname from pg_class c join pg_namespace n on n.oid = c.relnamespace
--    where n.nspname = 'public' and c.relkind = 'r' and not c.relrowsecurity; -- expect no rows

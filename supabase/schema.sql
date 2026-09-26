-- Run once in the Supabase SQL editor.
create table if not exists profiles (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  profile jsonb not null,
  resume jsonb,
  roadmap jsonb
);

create table if not exists interviews (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  profile_id uuid not null references profiles (id) on delete cascade,
  company text not null,
  kind text not null,
  messages jsonb not null default '[]'::jsonb,
  finished boolean not null default false
);

-- The backend uses the service-role key, which bypasses RLS.
-- RLS with no policies keeps the anon key from reading anything.
alter table profiles enable row level security;
alter table interviews enable row level security;

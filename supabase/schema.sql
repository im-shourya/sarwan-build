-- Run in the Supabase SQL editor (safe to re-run).
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

create table if not exists problems (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  profile_id uuid not null references profiles (id) on delete cascade,
  topic text not null,
  difficulty text not null,
  problem jsonb not null
);

create table if not exists submissions (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  profile_id uuid not null references profiles (id) on delete cascade,
  problem_id uuid references problems (id) on delete set null,
  language text not null,
  code text not null,
  review jsonb not null
);

create table if not exists quizzes (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  profile_id uuid not null references profiles (id) on delete cascade,
  topic text not null,
  category text not null,
  questions jsonb not null,
  answers jsonb,
  score int,
  total int not null,
  submitted_at timestamptz
);

create index if not exists problems_profile_idx on problems (profile_id);
create index if not exists submissions_profile_idx on submissions (profile_id);
create index if not exists quizzes_profile_idx on quizzes (profile_id);
create index if not exists interviews_profile_idx on interviews (profile_id);

alter table problems enable row level security;
alter table submissions enable row level security;
alter table quizzes enable row level security;

-- Accounts: one profile per Supabase Auth user.
alter table profiles add column if not exists user_id uuid unique references auth.users (id) on delete cascade;
alter table profiles add column if not exists completed_topics jsonb not null default '[]'::jsonb;
alter table profiles add column if not exists updated_at timestamptz not null default now();

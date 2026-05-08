-- Initial schema for AI Digest Bot.
-- Apply via Supabase Studio SQL editor or `supabase db push` locally.

begin;

create extension if not exists pgcrypto;

-- USERS -----------------------------------------------------------

create table users (
  id uuid primary key default gen_random_uuid(),
  tg_user_id bigint unique not null,
  tg_username text,
  tz text default 'Europe/Vilnius',
  digest_time time default '08:00',
  notion_root_page_id text,
  created_at timestamptz default now()
);

-- PROJECTS --------------------------------------------------------

create table projects (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references users(id) on delete cascade,
  slug text not null,
  name text not null,
  notion_page_id text,
  description text,
  stack text,
  ai_use_cases jsonb,
  keywords text[] default '{}',
  anti_keywords text[] default '{}',
  is_active boolean default true,
  last_synced_at timestamptz,
  sync_status text,
  created_at timestamptz default now(),
  unique(user_id, slug)
);

create index idx_projects_user on projects(user_id);

-- SOURCES ---------------------------------------------------------

create table sources (
  id uuid primary key default gen_random_uuid(),
  kind text not null,
  url text not null,
  name text not null,
  lang text not null,
  is_active boolean default true,
  last_fetched_at timestamptz,
  etag text,
  fail_count int default 0,
  created_at timestamptz default now()
);

create index idx_sources_active on sources(is_active);

-- RAW ITEMS -------------------------------------------------------

create table raw_items (
  id uuid primary key default gen_random_uuid(),
  source_id uuid references sources(id) on delete cascade,
  url text not null,
  url_hash text not null,
  title text,
  content text,
  published_at timestamptz,
  fetched_at timestamptz default now(),
  unique(url_hash)
);
create index idx_raw_items_fetched_at on raw_items(fetched_at);
create index idx_raw_items_source on raw_items(source_id);

-- PROCESSED ITEMS -------------------------------------------------

create table processed_items (
  id uuid primary key default gen_random_uuid(),
  raw_item_id uuid references raw_items(id) on delete cascade unique,
  user_id uuid references users(id) on delete cascade,
  tldr text not null,
  summary text not null,
  category text not null,
  is_noise boolean default false,
  global_score int not null,
  learning_value int not null default 0,
  project_scores jsonb not null,
  matched_projects text[],
  trend_tag boolean default false,
  topics text[],
  reasoning text,
  processed_at timestamptz default now()
);
create index idx_processed_items_user_date on processed_items(user_id, processed_at desc);
create index idx_processed_items_noise on processed_items(is_noise);
create index idx_processed_items_topics on processed_items using gin(topics);

-- DIGESTS ---------------------------------------------------------

create table digests (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references users(id) on delete cascade,
  digest_date date not null,
  tg_message_id bigint,
  item_ids uuid[] not null,
  noise_filtered_count int default 0,
  created_at timestamptz default now(),
  unique(user_id, digest_date)
);

create table weekly_briefs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references users(id) on delete cascade,
  period_start date not null,
  period_end date not null,
  content text not null,
  item_ids uuid[],
  created_at timestamptz default now(),
  unique(user_id, period_start)
);

create table monthly_landscapes (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references users(id) on delete cascade,
  period_start date not null,
  period_end date not null,
  content text not null,
  created_at timestamptz default now(),
  unique(user_id, period_start)
);

-- FEEDBACK & CHAT -------------------------------------------------

create table feedback (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references users(id) on delete cascade,
  processed_item_id uuid references processed_items(id) on delete cascade,
  reaction text not null,
  created_at timestamptz default now()
);
create index idx_feedback_user_date on feedback(user_id, created_at desc);

create table chat_messages (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references users(id) on delete cascade,
  role text not null,
  content text not null,
  meta jsonb,
  created_at timestamptz default now()
);
create index idx_chat_messages_user_date on chat_messages(user_id, created_at desc);

-- PREFERENCES & STATE ---------------------------------------------

create table user_preferences (
  user_id uuid primary key references users(id) on delete cascade,
  likes text[] default '{}',
  dislikes text[] default '{}',
  preferred_depth text default 'balanced',
  preferred_lang text[] default '{ru,en}',
  updated_at timestamptz default now()
);

create table bot_state (
  key text primary key,
  value jsonb not null,
  updated_at timestamptz default now()
);

-- SYNC LOG --------------------------------------------------------

create table sync_log (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references users(id) on delete cascade,
  triggered_by text not null,
  status text not null,
  projects_synced int default 0,
  errors jsonb,
  duration_ms int,
  created_at timestamptz default now()
);

commit;

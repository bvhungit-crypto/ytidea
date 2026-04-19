-- ================================================================
-- YouTube Idea Engine — Supabase Schema
-- ================================================================

create extension if not exists vector;

-- ── 1. CHANNELS ──────────────────────────────────────────────────
create table if not exists channels (
  channel_id         uuid primary key default gen_random_uuid(),
  name               text not null,
  youtube_channel_id text not null unique,
  seed_keywords      text[] not null default '{}',
  competitor_ids     text[] not null default '{}',
  tone               text not null default 'friendly',
  audience_profile   jsonb not null default '{
    "age_range": "18-35",
    "interests": [],
    "pain_points": [],
    "language_style": "casual"
  }',
  scoring_weights    jsonb not null default '{
    "trend": 0.40,
    "competition": 0.35,
    "keyword_match": 0.25
  }',
  topic_ban_list     text[] not null default '{}',
  cooldown_days      int not null default 30,
  active             boolean not null default true,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);

-- ── 2. IDEAS ─────────────────────────────────────────────────────
create table if not exists ideas (
  idea_id              uuid primary key default gen_random_uuid(),
  channel_id           uuid not null references channels(channel_id) on delete cascade,
  source               text not null,
  raw_signal           text not null,
  title_options        jsonb not null default '[]',
  best_title           text,
  hook                 text,
  outline              jsonb not null default '[]',
  localized_context    text,
  tags                 text[] not null default '{}',
  scores               jsonb not null default '{}',
  final_score          float not null default 0,
  tier                 char(1) not null default 'C',
  status               text not null default 'pending',
  reject_reason        text,
  youtube_video_id     text,
  published_at         timestamptz,
  actual_views_7d      int,
  actual_ctr_7d        float,
  actual_retention_7d  float,
  actual_views_30d     int,
  actual_ctr_30d       float,
  actual_retention_30d float,
  performance_vs_avg   float,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now()
);

create index if not exists idx_ideas_channel_id  on ideas(channel_id);
create index if not exists idx_ideas_status      on ideas(status);
create index if not exists idx_ideas_tier        on ideas(tier);
create index if not exists idx_ideas_created_at  on ideas(created_at desc);
create index if not exists idx_ideas_final_score on ideas(final_score desc);

-- ── 3. IDEA EMBEDDINGS ───────────────────────────────────────────
create table if not exists idea_embeddings (
  embedding_id uuid primary key default gen_random_uuid(),
  idea_id      uuid not null references ideas(idea_id) on delete cascade,
  channel_id   uuid not null references channels(channel_id) on delete cascade,
  content      text not null,
  embedding    vector(1536),
  created_at   timestamptz not null default now()
);

-- ── 4. API QUOTA LOG ─────────────────────────────────────────────
create table if not exists api_quota_log (
  log_id         uuid primary key default gen_random_uuid(),
  channel_id     uuid references channels(channel_id) on delete set null,
  run_date       date not null default current_date,
  pipeline_stage text not null,
  model          text,
  input_tokens   int not null default 0,
  output_tokens  int not null default 0,
  cost_usd       float not null default 0,
  youtube_units  int not null default 0,
  created_at     timestamptz not null default now()
);

-- ── 5. PIPELINE RUN LOG ──────────────────────────────────────────
create table if not exists pipeline_runs (
  run_id            uuid primary key default gen_random_uuid(),
  channel_id        uuid not null references channels(channel_id),
  run_date          date not null default current_date,
  status            text not null default 'running',
  raw_signals_count int not null default 0,
  after_filter      int not null default 0,
  after_dedup       int not null default 0,
  ideas_generated   int not null default 0,
  ideas_tier_a      int not null default 0,
  runtime_seconds   float,
  error_message     text,
  started_at        timestamptz not null default now(),
  finished_at       timestamptz
);

-- ── 6. AUTO-UPDATE updated_at ────────────────────────────────────
create or replace function update_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

create trigger trg_channels_updated_at
  before update on channels
  for each row execute function update_updated_at();

create trigger trg_ideas_updated_at
  before update on ideas
  for each row execute function update_updated_at();

-- ── 7. VIEWS ─────────────────────────────────────────────────────
create or replace view v_today_top_ideas as
select
  i.idea_id, c.name as channel_name,
  i.best_title, i.final_score, i.tier, i.status,
  i.scores, i.tags, i.created_at
from ideas i
join channels c on c.channel_id = i.channel_id
where i.created_at::date = current_date
  and i.tier = 'A'
order by i.final_score desc;

create or replace view v_cost_today as
select
  c.name as channel_name,
  q.pipeline_stage,
  q.model,
  sum(q.input_tokens)  as total_input_tokens,
  sum(q.output_tokens) as total_output_tokens,
  sum(q.cost_usd)      as total_cost_usd,
  sum(q.youtube_units) as total_yt_units
from api_quota_log q
join channels c on c.channel_id = q.channel_id
where q.run_date = current_date
group by c.name, q.pipeline_stage, q.model
order by total_cost_usd desc;
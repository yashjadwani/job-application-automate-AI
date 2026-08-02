-- CV Tailoring Platform — Supabase schema (PRD v1.1 §5)
-- Run in the Supabase SQL editor. RLS on every table: tenant isolation is P0.

-- ---------------------------------------------------------------------------
-- profiles
-- ---------------------------------------------------------------------------
create table if not exists public.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  name text,
  email text,
  linkedin_url text,
  bio text,
  skills text[] default '{}',
  additional_context text,
  updated_at timestamptz default now()
);

alter table public.profiles enable row level security;

create policy "profiles_select_own" on public.profiles
  for select using (id = auth.uid());
create policy "profiles_insert_own" on public.profiles
  for insert with check (id = auth.uid());
create policy "profiles_update_own" on public.profiles
  for update using (id = auth.uid());

-- ---------------------------------------------------------------------------
-- cv_structure
-- ---------------------------------------------------------------------------
create table if not exists public.cv_structure (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  personal jsonb default '{}',
  sections jsonb default '[]',          -- [{ id, title, date, bullets: [{ index, text }] }]
  original_docx_url text,               -- Storage path
  original_filename text,               -- the user's uploaded filename (for export naming)
  updated_at timestamptz default now(),
  unique (user_id)
);

-- If cv_structure already exists (existing project), add the new column:
alter table public.cv_structure add column if not exists original_filename text;

alter table public.cv_structure enable row level security;

create policy "cv_select_own" on public.cv_structure
  for select using (user_id = auth.uid());
create policy "cv_insert_own" on public.cv_structure
  for insert with check (user_id = auth.uid());
create policy "cv_update_own" on public.cv_structure
  for update using (user_id = auth.uid());
create policy "cv_delete_own" on public.cv_structure
  for delete using (user_id = auth.uid());

-- ---------------------------------------------------------------------------
-- analyses
-- ---------------------------------------------------------------------------
create table if not exists public.analyses (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  jd_text text not null,
  jd_title text,
  company_name text,
  user_notes text,
  status text not null default 'pending'
    check (status in ('pending','researching','analysing','writing',
                      'awaiting_approval','reviewing','done','failed')),
  app_status text not null default 'not_applied'
    check (app_status in ('not_applied','applied','interviewing','offer','rejected')),
  error text,
  agent_trace jsonb default '[]',       -- [{ agent, action, detail }] — live activity log
  employer_research jsonb,              -- { findings: [{category, insight, sources[]}], talking_points: [] }
  match_score integer check (match_score between 0 and 100),
  match_summary text,                   -- stored so HITL resume can build the cover letter
  gaps jsonb default '[]',
  matched_skills jsonb default '[]',
  ats_score integer check (ats_score between 0 and 100),
  ats_keywords jsonb,                   -- { present: [], missing: [] }
  rewritten_bullets jsonb,              -- { section_id: [bullet, ...] }
  cover_letter_text text,
  created_at timestamptz default now()
);

alter table public.analyses enable row level security;

create policy "analyses_select_own" on public.analyses
  for select using (user_id = auth.uid());
create policy "analyses_insert_own" on public.analyses
  for insert with check (user_id = auth.uid());
create policy "analyses_update_own" on public.analyses
  for update using (user_id = auth.uid());
create policy "analyses_delete_own" on public.analyses
  for delete using (user_id = auth.uid());

create index if not exists analyses_user_created_idx
  on public.analyses (user_id, created_at desc);

-- ---------------------------------------------------------------------------
-- llm_calls — telemetry: one row per OpenAI API call (tokens, latency, cost)
-- ---------------------------------------------------------------------------
create table if not exists public.llm_calls (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  analysis_id uuid references public.analyses (id) on delete set null,
  label text not null,                  -- e.g. research_web_search, analyst_tool_loop
  kind text default 'chat',             -- chat | responses
  provider text,                        -- opencode | openrouter | gemini
  model text,                           -- the exact model id used
  status text default 'ok',             -- ok | error
  error text,
  latency_ms integer,
  prompt_tokens integer,
  completion_tokens integer,
  total_tokens integer,
  cost_usd numeric(10, 6),
  response text,                         -- the model's output (truncated to 8k)
  created_at timestamptz default now()
);

-- If llm_calls already exists (existing project), add the new columns:
alter table public.llm_calls add column if not exists provider text;
alter table public.llm_calls add column if not exists response text;

alter table public.llm_calls enable row level security;

create policy "llm_select_own" on public.llm_calls
  for select using (user_id = auth.uid());
create policy "llm_insert_own" on public.llm_calls
  for insert with check (user_id = auth.uid());

create index if not exists llm_calls_user_created_idx
  on public.llm_calls (user_id, created_at desc);
create index if not exists llm_calls_analysis_idx
  on public.llm_calls (analysis_id);

-- ---------------------------------------------------------------------------
-- analysis_events — per-agent execution trail: one row per agent stage, with
-- wall-clock timing (includes tool calls/retries, unlike llm_calls which is
-- per LLM request). Append-only; powers "how long did each agent take".
-- ---------------------------------------------------------------------------
create table if not exists public.analysis_events (
  id uuid primary key default gen_random_uuid(),
  analysis_id uuid not null references public.analyses (id) on delete cascade,
  user_id uuid not null references auth.users (id) on delete cascade,
  agent text not null,                  -- research | match | ats | rewrite | critic | cover_letter | editor
  stage text,                           -- the analyses.status this ran under (researching, analysing, …)
  status text not null default 'ok'     -- ok | error | skipped
    check (status in ('ok','error','skipped')),
  detail text,
  error text,
  started_at timestamptz not null default now(),
  duration_ms integer,
  created_at timestamptz not null default now()
);

alter table public.analysis_events enable row level security;

create policy "events_select_own" on public.analysis_events
  for select using (user_id = auth.uid());
create policy "events_insert_own" on public.analysis_events
  for insert with check (user_id = auth.uid());

create index if not exists analysis_events_analysis_idx
  on public.analysis_events (analysis_id, started_at);
create index if not exists analysis_events_user_agent_idx
  on public.analysis_events (user_id, agent);

-- ---------------------------------------------------------------------------
-- telegram_links — connects a Telegram chat to a user (bot integration)
-- ---------------------------------------------------------------------------
create table if not exists public.telegram_links (
  user_id uuid primary key references auth.users (id) on delete cascade,
  chat_id bigint unique,
  link_code text unique,
  created_at timestamptz default now()
);

alter table public.telegram_links enable row level security;

-- The user manages their own link from the web app; the bot webhook uses the
-- service role (bypasses RLS) and always filters by resolved user_id.
create policy "tg_select_own" on public.telegram_links
  for select using (user_id = auth.uid());
create policy "tg_insert_own" on public.telegram_links
  for insert with check (user_id = auth.uid());
create policy "tg_update_own" on public.telegram_links
  for update using (user_id = auth.uid());
create policy "tg_delete_own" on public.telegram_links
  for delete using (user_id = auth.uid());

-- ---------------------------------------------------------------------------
-- Storage buckets (create via dashboard or here) + per-user path policies
-- ---------------------------------------------------------------------------
insert into storage.buckets (id, name, public) values ('cv-originals', 'cv-originals', false)
  on conflict (id) do nothing;
insert into storage.buckets (id, name, public) values ('exports', 'exports', false)
  on conflict (id) do nothing;

-- Objects are only accessible under the caller's {user_id}/ prefix
create policy "cv_originals_rw_own" on storage.objects
  for all using (
    bucket_id = 'cv-originals'
    and (storage.foldername(name))[1] = auth.uid()::text
  )
  with check (
    bucket_id = 'cv-originals'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

create policy "exports_rw_own" on storage.objects
  for all using (
    bucket_id = 'exports'
    and (storage.foldername(name))[1] = auth.uid()::text
  )
  with check (
    bucket_id = 'exports'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

-- v16.4: an independent, cost-bounded Gemini research layer.
-- It can read fixed quantitative results but has no trigger, foreign key, or
-- write path back into stock_analysis_cache/opportunity_score_history.

create table if not exists public.ai_stock_research (
  id bigint generated always as identity primary key,
  symbol text not null references public.stock_master(symbol) on delete cascade,
  group_name text not null check (group_name in ('listed', 'otc', 'etf')),
  data_date date,
  input_hash text not null check (length(input_hash) = 64),
  provider text not null default 'google-gemini',
  model text not null,
  schema_version text not null,
  status text not null default 'ready' check (status in ('ready', 'error')),
  selected_reason text not null,
  verdict text not null check (verdict in ('偏多觀察', '中性觀察', '風險升高')),
  ai_confidence numeric not null check (ai_confidence between 0 and 100),
  analysis jsonb not null,
  input_snapshot jsonb not null default '{}'::jsonb,
  generated_at timestamptz not null default now(),
  expires_at timestamptz,
  unique (symbol, input_hash, model, schema_version)
);

create index if not exists ai_stock_research_latest_idx
  on public.ai_stock_research (symbol, generated_at desc)
  where status = 'ready';
create index if not exists ai_stock_research_group_idx
  on public.ai_stock_research (group_name, generated_at desc)
  where status = 'ready';

create table if not exists public.ai_research_runs (
  id uuid primary key default extensions.gen_random_uuid(),
  status text not null check (status in ('running', 'success', 'partial', 'error')),
  provider text not null default 'google-gemini',
  model text not null,
  schema_version text not null,
  selected_count integer not null default 0 check (selected_count >= 0),
  attempted_count integer not null default 0 check (attempted_count >= 0),
  generated_count integer not null default 0 check (generated_count >= 0),
  failed_count integer not null default 0 check (failed_count >= 0),
  details jsonb not null default '{}'::jsonb,
  last_error text,
  started_at timestamptz not null default now(),
  finished_at timestamptz
);
create index if not exists ai_research_runs_started_idx on public.ai_research_runs (started_at desc);

create table if not exists public.ai_research_usage (
  usage_date date primary key,
  reserved_calls integer not null default 0 check (reserved_calls >= 0),
  completed_calls integer not null default 0 check (completed_calls >= 0),
  failed_calls integer not null default 0 check (failed_calls >= 0),
  updated_at timestamptz not null default now()
);

alter table public.ai_stock_research enable row level security;
alter table public.ai_research_runs enable row level security;
alter table public.ai_research_usage enable row level security;

drop policy if exists ai_stock_research_public_read on public.ai_stock_research;
create policy ai_stock_research_public_read on public.ai_stock_research
  for select to anon, authenticated using (status = 'ready');

revoke all on public.ai_stock_research, public.ai_research_runs, public.ai_research_usage
  from anon, authenticated;
grant select (
  id, symbol, group_name, data_date, provider, model, schema_version, selected_reason,
  verdict, ai_confidence, analysis, generated_at, expires_at
) on public.ai_stock_research to anon, authenticated;

grant all on public.ai_stock_research, public.ai_research_runs, public.ai_research_usage to service_role;
grant usage, select on sequence public.ai_stock_research_id_seq to service_role;

create or replace function public.twss_reserve_ai_calls(
  p_requested integer,
  p_daily_limit integer default 12
)
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_date date := (clock_timestamp() at time zone 'Asia/Taipei')::date;
  v_limit integer := greatest(1, least(20, coalesce(p_daily_limit, 12)));
  v_requested integer := greatest(0, least(20, coalesce(p_requested, 0)));
  v_used integer;
  v_allowed integer;
begin
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('twss-ai-daily-quota', 0));
  insert into public.ai_research_usage (usage_date) values (v_date)
  on conflict (usage_date) do nothing;
  select reserved_calls into v_used
  from public.ai_research_usage where usage_date = v_date for update;
  v_allowed := least(v_requested, greatest(0, v_limit - coalesce(v_used, 0)));
  update public.ai_research_usage
  set reserved_calls = reserved_calls + v_allowed, updated_at = clock_timestamp()
  where usage_date = v_date;
  return v_allowed;
end;
$$;

create or replace function public.twss_finish_ai_calls(
  p_completed integer,
  p_failed integer
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_date date := (clock_timestamp() at time zone 'Asia/Taipei')::date;
begin
  insert into public.ai_research_usage (usage_date, completed_calls, failed_calls)
  values (v_date, greatest(0, coalesce(p_completed, 0)), greatest(0, coalesce(p_failed, 0)))
  on conflict (usage_date) do update
    set completed_calls = public.ai_research_usage.completed_calls + excluded.completed_calls,
        failed_calls = public.ai_research_usage.failed_calls + excluded.failed_calls,
        updated_at = clock_timestamp();
end;
$$;

revoke all on function public.twss_reserve_ai_calls(integer, integer) from public, anon, authenticated;
revoke all on function public.twss_finish_ai_calls(integer, integer) from public, anon, authenticated;
grant execute on function public.twss_reserve_ai_calls(integer, integer) to service_role;
grant execute on function public.twss_finish_ai_calls(integer, integer) to service_role;

insert into public.stock_sync_state (job_key, group_name)
values ('ai_research', null)
on conflict (job_key) do nothing;

do $$
declare
  existing_job bigint;
begin
  for existing_job in select jobid from cron.job where jobname = 'twss-ai-research-weekday'
  loop
    perform cron.unschedule(existing_job);
  end loop;
end
$$;

-- pg_cron uses UTC. 10:20 UTC is 18:20 in Taiwan, after the daily market
-- snapshot and several deep-data accumulation windows have completed.
select cron.schedule(
  'twss-ai-research-weekday',
  '20 10 * * 1-5',
  $job$
    select net.http_post(
      url := 'https://lfkdkdyaatdlizryiyon.supabase.co/functions/v1/twss-ai-research',
      headers := jsonb_build_object(
        'Content-Type', 'application/json',
        'x-twss-sync-token', (
          select decrypted_secret from vault.decrypted_secrets where name = 'twss_sync_token'
        )
      ),
      body := '{"limit":12}'::jsonb,
      timeout_milliseconds := 300000
    );
  $job$
);

comment on table public.ai_stock_research is
  'Independent Gemini research summaries. Never used as input to the quantitative ranking engine.';
comment on column public.ai_stock_research.input_hash is
  'Deterministic hash of the bounded public-data snapshot; unchanged inputs are not regenerated.';

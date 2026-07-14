-- v16.5: AI research is manual-only.  Quantitative scores and rankings remain
-- read-only inputs, while cached summaries, per-user limits, and global cost
-- limits are claimed atomically before a Gemini request starts.

alter table public.ai_research_runs
  add column if not exists mode text not null default 'batch'
    check (mode in ('batch', 'manual')),
  add column if not exists symbol text references public.stock_master(symbol) on delete set null,
  add column if not exists input_hash text check (input_hash is null or length(input_hash) = 64),
  add column if not exists requester_hash text check (requester_hash is null or length(requester_hash) = 64);

create index if not exists ai_research_runs_manual_input_idx
  on public.ai_research_runs (symbol, input_hash, model, schema_version, started_at desc)
  where mode = 'manual';

create index if not exists ai_research_runs_manual_requester_idx
  on public.ai_research_runs (requester_hash, started_at desc)
  where mode = 'manual';

create or replace function public.twss_claim_manual_ai_request(
  p_symbol text,
  p_input_hash text,
  p_model text,
  p_schema_version text,
  p_requester_hash text,
  p_daily_limit integer default 12,
  p_user_daily_limit integer default 6
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_date date := (clock_timestamp() at time zone 'Asia/Taipei')::date;
  v_global_limit integer := greatest(1, least(20, coalesce(p_daily_limit, 12)));
  v_user_limit integer := greatest(1, least(12, coalesce(p_user_daily_limit, 6)));
  v_recent_count integer;
  v_active_count integer;
  v_reserved integer;
  v_run_id uuid;
begin
  if p_symbol !~ '^[0-9]{4,6}[A-Za-z]?$'
    or length(coalesce(p_input_hash, '')) <> 64
    or length(coalesce(p_requester_hash, '')) <> 64
    or nullif(trim(coalesce(p_model, '')), '') is null
    or nullif(trim(coalesce(p_schema_version, '')), '') is null
  then
    raise exception 'invalid manual AI request';
  end if;

  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('twss-ai-manual:' || p_symbol || ':' || p_input_hash, 0)
  );

  if exists (
    select 1
    from public.ai_stock_research
    where symbol = p_symbol
      and input_hash = p_input_hash
      and model = p_model
      and schema_version = p_schema_version
      and status = 'ready'
      and (expires_at is null or expires_at > clock_timestamp())
  ) then
    return pg_catalog.jsonb_build_object('action', 'cached');
  end if;

  if exists (
    select 1
    from public.ai_research_runs
    where mode = 'manual'
      and symbol = p_symbol
      and input_hash = p_input_hash
      and model = p_model
      and schema_version = p_schema_version
      and status = 'running'
      and started_at > clock_timestamp() - interval '3 minutes'
  ) then
    return pg_catalog.jsonb_build_object('action', 'in_progress');
  end if;

  select count(*) into v_recent_count
  from public.ai_research_runs
  where mode = 'manual'
    and requester_hash = p_requester_hash
    and (started_at at time zone 'Asia/Taipei')::date = v_date;

  if v_recent_count >= v_user_limit then
    return pg_catalog.jsonb_build_object('action', 'user_limit');
  end if;

  select count(*) into v_active_count
  from public.ai_research_runs
  where mode = 'manual'
    and status = 'running'
    and started_at > clock_timestamp() - interval '3 minutes';

  if v_active_count >= 2 then
    return pg_catalog.jsonb_build_object('action', 'busy');
  end if;

  v_reserved := public.twss_reserve_ai_calls(1, v_global_limit);
  if coalesce(v_reserved, 0) < 1 then
    return pg_catalog.jsonb_build_object('action', 'global_limit');
  end if;

  insert into public.ai_research_runs (
    status, provider, model, schema_version, selected_count, attempted_count,
    mode, symbol, input_hash, requester_hash, details, started_at
  ) values (
    'running', 'google-gemini', p_model, p_schema_version, 1, 1,
    'manual', p_symbol, p_input_hash, p_requester_hash,
    pg_catalog.jsonb_build_object('trigger', 'detail-button'), clock_timestamp()
  ) returning id into v_run_id;

  return pg_catalog.jsonb_build_object('action', 'generate', 'run_id', v_run_id);
end;
$$;

create or replace function public.twss_finish_manual_ai_request(
  p_run_id uuid,
  p_success boolean,
  p_error_code text default null
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_updated integer := 0;
begin
  update public.ai_research_runs
  set status = case when p_success then 'success' else 'error' end,
      generated_count = case when p_success then 1 else 0 end,
      failed_count = case when p_success then 0 else 1 end,
      details = coalesce(details, '{}'::jsonb) || pg_catalog.jsonb_build_object(
        'errorCode', case when p_success then null else left(coalesce(p_error_code, 'AI_PROVIDER_ERROR'), 80) end
      ),
      last_error = case when p_success then null else left(coalesce(p_error_code, 'AI_PROVIDER_ERROR'), 80) end,
      finished_at = clock_timestamp()
  where id = p_run_id and mode = 'manual' and status = 'running';

  get diagnostics v_updated = row_count;
  if v_updated = 1 then
    perform public.twss_finish_ai_calls(
      case when p_success then 1 else 0 end,
      case when p_success then 0 else 1 end
    );
  end if;
end;
$$;

revoke all on function public.twss_claim_manual_ai_request(text, text, text, text, text, integer, integer)
  from public, anon, authenticated;
revoke all on function public.twss_finish_manual_ai_request(uuid, boolean, text)
  from public, anon, authenticated;
grant execute on function public.twss_claim_manual_ai_request(text, text, text, text, text, integer, integer)
  to service_role;
grant execute on function public.twss_finish_manual_ai_request(uuid, boolean, text)
  to service_role;

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

update public.stock_sync_state
set status = 'success',
    last_error = null,
    details = (
      coalesce(details, '{}'::jsonb)
      - 'nextScheduled' - 'dailyLimitReached' - 'selected' - 'generated' - 'reason'
    ) || pg_catalog.jsonb_build_object(
      'version', '16.5-ai-manual',
      'mode', 'manual-only',
      'scheduled', false,
      'userDailyLimit', 6,
      'dailyLimit', 12
    ),
    updated_at = clock_timestamp()
where job_key = 'ai_research';

comment on function public.twss_claim_manual_ai_request(text, text, text, text, text, integer, integer) is
  'Service-role-only atomic cache, concurrency, per-user, and global quota gate for manual AI research.';

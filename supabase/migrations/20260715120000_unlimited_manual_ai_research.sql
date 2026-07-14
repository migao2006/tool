-- v16.6: manual AI research no longer has application-level daily quotas.
-- Authentication, exact-input cache reuse, per-symbol deduplication and the
-- two-request global concurrency guard remain in place.  The legacy limit
-- parameters stay in the signature for a zero-downtime Edge Function rollout.

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
  v_active_count integer;
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

  -- A symbol-specific lock prevents duplicate work for the same input.  This
  -- second, fixed lock makes the global active-count check plus insert atomic
  -- across different symbols, so removing quotas cannot race past the
  -- two-request provider concurrency guard.
  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('twss-ai-manual-concurrency', 0)
  );

  select count(*) into v_active_count
  from public.ai_research_runs
  where mode = 'manual'
    and status = 'running'
    and started_at > clock_timestamp() - interval '3 minutes';

  if v_active_count >= 2 then
    return pg_catalog.jsonb_build_object('action', 'busy');
  end if;

  insert into public.ai_research_runs (
    status, provider, model, schema_version, selected_count, attempted_count,
    mode, symbol, input_hash, requester_hash, details, started_at
  ) values (
    'running', 'google-gemini', p_model, p_schema_version, 1, 1,
    'manual', p_symbol, p_input_hash, p_requester_hash,
    pg_catalog.jsonb_build_object(
      'trigger', 'detail-button',
      'quotaMode', 'unlimited'
    ),
    clock_timestamp()
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

create or replace function public.twss_prune_history()
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  snapshot_rows integer := 0;
  price_rows integer := 0;
  flow_rows integer := 0;
  margin_rows integer := 0;
  score_rows integer := 0;
  ai_run_rows integer := 0;
  expired_ai_rows integer := 0;
begin
  delete from public.stock_snapshots
  where trade_date < current_date - 60;
  get diagnostics snapshot_rows = row_count;

  delete from public.stock_price_history
  where trade_date < current_date - 550;
  get diagnostics price_rows = row_count;

  delete from public.stock_institutional_flows
  where trade_date < current_date - 180;
  get diagnostics flow_rows = row_count;

  delete from public.stock_margin_history
  where trade_date < current_date - 270;
  get diagnostics margin_rows = row_count;

  delete from public.opportunity_score_history
  where score_date < current_date - 730;
  get diagnostics score_rows = row_count;

  delete from public.ai_research_runs
  where started_at < clock_timestamp() - interval '90 days';
  get diagnostics ai_run_rows = row_count;

  delete from public.ai_stock_research
  where expires_at is not null
    and expires_at < clock_timestamp() - interval '30 days';
  get diagnostics expired_ai_rows = row_count;

  return pg_catalog.jsonb_build_object(
    'stock_snapshots', snapshot_rows,
    'stock_price_history', price_rows,
    'stock_institutional_flows', flow_rows,
    'stock_margin_history', margin_rows,
    'opportunity_score_history', score_rows,
    'ai_research_runs', ai_run_rows,
    'expired_ai_stock_research', expired_ai_rows,
    'pruned_at', clock_timestamp()
  );
end;
$$;

revoke all on function public.twss_prune_history() from public, anon, authenticated;
grant execute on function public.twss_prune_history() to service_role;

update public.stock_sync_state
set status = 'success',
    last_error = null,
    details = (
      coalesce(details, '{}'::jsonb)
      - 'userDailyLimit' - 'dailyLimit' - 'dailyLimitReached' - 'nextScheduled'
    ) || pg_catalog.jsonb_build_object(
      'version', '16.6-ai-manual-unlimited',
      'mode', 'manual-only',
      'scheduled', false,
      'quotaMode', 'unlimited',
      'maxConcurrent', 2
    ),
    updated_at = clock_timestamp()
where job_key = 'ai_research';

comment on function public.twss_claim_manual_ai_request(text, text, text, text, text, integer, integer) is
  'Service-role-only atomic cache, deduplication and concurrency gate for unlimited manual AI research. Legacy daily-limit arguments are ignored.';

comment on function public.twss_finish_manual_ai_request(uuid, boolean, text) is
  'Completes a manual AI run without reserving or charging the legacy daily application quota ledger.';

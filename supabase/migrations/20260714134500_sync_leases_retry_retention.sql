-- Prevent duplicate cron/manual batches, retain retry diagnostics, and keep the
-- Free-plan database from growing without bound.

alter table public.stock_sync_state
  add column if not exists lease_owner text,
  add column if not exists lease_until timestamptz;

alter table public.stock_analysis_cache
  add column if not exists attempt_count integer not null default 0 check (attempt_count >= 0),
  add column if not exists next_retry_at timestamptz,
  add column if not exists error_kind text;

create index if not exists stock_analysis_cache_retry_idx
  on public.stock_analysis_cache (group_name, next_retry_at)
  where status = 'error';

create or replace function public.twss_claim_sync_lease(
  p_job_key text,
  p_owner text,
  p_seconds integer default 180
)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
  changed integer;
begin
  update public.stock_sync_state
  set lease_owner = p_owner,
      lease_until = clock_timestamp() + make_interval(secs => greatest(30, least(300, p_seconds))),
      updated_at = clock_timestamp()
  where job_key = p_job_key
    and (
      lease_until is null
      or lease_until < clock_timestamp()
      or lease_owner = p_owner
    );
  get diagnostics changed = row_count;
  return changed = 1;
end;
$$;

create or replace function public.twss_release_sync_lease(
  p_job_key text,
  p_owner text
)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
  changed integer;
begin
  update public.stock_sync_state
  set lease_owner = null,
      lease_until = null,
      updated_at = clock_timestamp()
  where job_key = p_job_key
    and lease_owner = p_owner;
  get diagnostics changed = row_count;
  return changed = 1;
end;
$$;

revoke all on function public.twss_claim_sync_lease(text, text, integer) from public, anon, authenticated;
revoke all on function public.twss_release_sync_lease(text, text) from public, anon, authenticated;
grant execute on function public.twss_claim_sync_lease(text, text, integer) to service_role;
grant execute on function public.twss_release_sync_lease(text, text) to service_role;

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

  return jsonb_build_object(
    'stock_snapshots', snapshot_rows,
    'stock_price_history', price_rows,
    'stock_institutional_flows', flow_rows,
    'stock_margin_history', margin_rows,
    'opportunity_score_history', score_rows,
    'pruned_at', clock_timestamp()
  );
end;
$$;

revoke all on function public.twss_prune_history() from public, anon, authenticated;
grant execute on function public.twss_prune_history() to service_role;

do $$
declare
  existing_job bigint;
begin
  for existing_job in
    select jobid from cron.job where jobname = 'twss-prune-history'
  loop
    perform cron.unschedule(existing_job);
  end loop;
end
$$;

select cron.schedule(
  'twss-prune-history',
  '30 7 * * *',
  $job$select public.twss_prune_history();$job$
);

-- v16.3 revalidates the existing cache because financial receivables and
-- confidence-depth logic changed.  Old ready rows remain visible until they
-- are replaced; only the progress counters restart.
update public.stock_sync_state
set cursor_offset = 0,
    processed_count = 0,
    status = 'pending',
    last_error = null,
    details = details || jsonb_build_object('revalidationVersion', '16.3'),
    updated_at = now()
where job_key in ('deep_listed', 'deep_otc', 'deep_etf');

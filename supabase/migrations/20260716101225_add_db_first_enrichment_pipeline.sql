-- v20 database-first analysis pipeline.
--
-- The official after-close database path can publish without waiting for the
-- rate-limited FinMind enrichment path.  Both new tables are intentionally
-- service-only; public clients continue to use the existing sanitized read
-- models and APIs.

create table if not exists public.stock_lending_history (
  symbol text not null references public.stock_master(symbol) on delete cascade,
  trade_date date not null,
  lending_value numeric,
  source text not null default 'FinMind TaiwanStockSecuritiesLending',
  raw_data jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default clock_timestamp(),
  primary key (symbol, trade_date)
);

create index if not exists stock_lending_history_date_idx
  on public.stock_lending_history (trade_date desc, symbol);

create table if not exists public.stock_enrichment_queue (
  id bigint generated always as identity primary key,
  symbol text not null references public.stock_master(symbol) on delete cascade,
  data_date date not null,
  group_name text not null check (group_name in ('listed', 'otc', 'etf')),
  dataset_key text not null check (
    dataset_key in ('lending', 'price', 'institutional', 'margin', 'revenue', 'financial')
  ),
  priority smallint not null default 100 check (priority between 0 and 1000),
  status text not null default 'pending' check (status in ('pending', 'running', 'success', 'error')),
  attempt_count integer not null default 0 check (attempt_count >= 0),
  max_attempts integer not null default 3 check (max_attempts between 1 and 20),
  next_retry_at timestamptz,
  lease_owner text,
  lease_until timestamptz,
  source_date date,
  details jsonb not null default '{}'::jsonb,
  error_kind text,
  last_error text,
  last_attempt_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz not null default clock_timestamp(),
  updated_at timestamptz not null default clock_timestamp(),
  constraint stock_enrichment_queue_symbol_date_dataset_key
    unique (symbol, data_date, dataset_key),
  constraint stock_enrichment_queue_lease_consistency check (
    (status = 'running' and lease_owner is not null and lease_until is not null)
    or (status <> 'running' and lease_owner is null and lease_until is null)
  )
);

-- The daily worker filters by date and state, then orders by priority and
-- retry time.  Keeping completed rows out of the claim indexes makes them
-- small while retaining an auditable daily completion record.
create index if not exists stock_enrichment_queue_claim_idx
  on public.stock_enrichment_queue
    (data_date desc, status, next_retry_at, priority desc, id)
  where status in ('pending', 'error');

create index if not exists stock_enrichment_queue_expired_lease_idx
  on public.stock_enrichment_queue (lease_until, data_date, priority desc, id)
  where status = 'running';

create index if not exists stock_enrichment_queue_dataset_status_idx
  on public.stock_enrichment_queue (data_date, dataset_key, status, priority desc);

alter table public.stock_lending_history enable row level security;
alter table public.stock_enrichment_queue enable row level security;

-- No anon/authenticated policy is created.  RLS plus explicit grants keeps the
-- tables inaccessible even when the public schema is exposed by the Data API.
revoke all on table
  public.stock_lending_history,
  public.stock_enrichment_queue
from public, anon, authenticated;

grant select, insert, update, delete on table
  public.stock_lending_history,
  public.stock_enrichment_queue
to service_role;

revoke all on sequence public.stock_enrichment_queue_id_seq
  from public, anon, authenticated;
grant usage, select on sequence public.stock_enrichment_queue_id_seq
  to service_role;

drop trigger if exists stock_lending_history_set_updated_at
  on public.stock_lending_history;
create trigger stock_lending_history_set_updated_at
before update on public.stock_lending_history
for each row execute function public.set_updated_at();

drop trigger if exists stock_enrichment_queue_set_updated_at
  on public.stock_enrichment_queue;
create trigger stock_enrichment_queue_set_updated_at
before update on public.stock_enrichment_queue
for each row execute function public.set_updated_at();

-- The new two-minute base/model cadence must not outlive the old 300-second
-- lease cap.  Successful workers release early, so a longer safety lease only
-- affects crashed or timed-out executions and prevents duplicate writes.
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
  v_changed integer := 0;
  v_minimum_seconds integer := case
    when p_job_key = 'v20_model' or p_job_key like 'deep\_%' escape '\' then 420
    else 30
  end;
  v_lease_seconds integer := greatest(
    v_minimum_seconds,
    least(600, coalesce(p_seconds, v_minimum_seconds))
  );
begin
  if nullif(pg_catalog.btrim(coalesce(p_job_key, '')), '') is null
    or nullif(pg_catalog.btrim(coalesce(p_owner, '')), '') is null
  then
    raise exception 'sync_lease_identity_required' using errcode = '22023';
  end if;

  update public.stock_sync_state
  set lease_owner = p_owner,
      lease_until = clock_timestamp() + pg_catalog.make_interval(secs => v_lease_seconds),
      updated_at = clock_timestamp()
  where job_key = p_job_key
    and (
      lease_until is null
      or lease_until < clock_timestamp()
      or lease_owner = p_owner
    );

  get diagnostics v_changed = row_count;
  return v_changed = 1;
end;
$$;

revoke all on function public.twss_claim_sync_lease(text, text, integer)
  from public, anon, authenticated;
grant execute on function public.twss_claim_sync_lease(text, text, integer)
  to service_role;

-- Atomically lease independent queue rows without making parallel workers wait
-- on each other.  Expired leases are reclaimable and every actual claim counts
-- as one attempt.
create or replace function public.twss_claim_enrichment_batch(
  p_owner text,
  p_limit integer default 50,
  p_lease_seconds integer default 180,
  p_dataset_keys text[] default null
)
returns setof public.stock_enrichment_queue
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_limit integer := greatest(1, least(coalesce(p_limit, 50), 200));
  -- One enrichment invocation can legitimately approach the 400-second Edge
  -- wall-clock ceiling.  Keep leases longer than that ceiling even when an
  -- older worker requests the former 180-second value.
  v_lease_seconds integer := greatest(420, least(coalesce(p_lease_seconds, 420), 600));
begin
  if nullif(pg_catalog.btrim(coalesce(p_owner, '')), '') is null then
    raise exception 'enrichment_owner_required' using errcode = '22023';
  end if;

  if p_dataset_keys is not null and exists (
    select 1
    from pg_catalog.unnest(p_dataset_keys) as requested(dataset_key)
    where requested.dataset_key not in (
      'lending', 'price', 'institutional', 'margin', 'revenue', 'financial'
    )
  ) then
    raise exception 'invalid_enrichment_dataset' using errcode = '22023';
  end if;

  return query
  with candidates as (
    select q.id
    from public.stock_enrichment_queue q
    where q.attempt_count < q.max_attempts
      and (p_dataset_keys is null or q.dataset_key = any(p_dataset_keys))
      and (
        (
          q.status in ('pending', 'error')
          and (q.next_retry_at is null or q.next_retry_at <= clock_timestamp())
        )
        or (
          q.status = 'running'
          and q.lease_until < clock_timestamp()
        )
      )
    order by q.data_date desc,
      q.priority desc,
      coalesce(q.next_retry_at, q.created_at),
      q.id
    limit v_limit
    for update skip locked
  )
  update public.stock_enrichment_queue q
  set status = 'running',
      attempt_count = q.attempt_count + 1,
      next_retry_at = null,
      lease_owner = p_owner,
      lease_until = clock_timestamp() + pg_catalog.make_interval(secs => v_lease_seconds),
      last_attempt_at = clock_timestamp(),
      completed_at = null,
      updated_at = clock_timestamp()
  from candidates c
  where q.id = c.id
  returning q.*;
end;
$$;

create or replace function public.twss_complete_enrichment(
  p_id bigint,
  p_owner text,
  p_source_date date default null,
  p_details jsonb default '{}'::jsonb
)
returns boolean
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_changed integer := 0;
begin
  if p_id is null or nullif(pg_catalog.btrim(coalesce(p_owner, '')), '') is null
    or pg_catalog.jsonb_typeof(coalesce(p_details, '{}'::jsonb)) <> 'object'
  then
    raise exception 'invalid_enrichment_completion' using errcode = '22023';
  end if;

  update public.stock_enrichment_queue q
  set status = 'success',
      source_date = coalesce(p_source_date, q.source_date),
      details = coalesce(q.details, '{}'::jsonb) || coalesce(p_details, '{}'::jsonb),
      error_kind = null,
      last_error = null,
      next_retry_at = null,
      lease_owner = null,
      lease_until = null,
      completed_at = clock_timestamp(),
      updated_at = clock_timestamp()
  where q.id = p_id
    and q.status = 'running'
    and q.lease_owner = p_owner;

  get diagnostics v_changed = row_count;
  return v_changed = 1;
end;
$$;

create or replace function public.twss_fail_enrichment(
  p_id bigint,
  p_owner text,
  p_error_kind text,
  p_last_error text,
  p_retry_after_seconds integer default 300
)
returns text
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_attempt_count integer;
  v_max_attempts integer;
begin
  if p_id is null or nullif(pg_catalog.btrim(coalesce(p_owner, '')), '') is null then
    raise exception 'invalid_enrichment_failure' using errcode = '22023';
  end if;

  update public.stock_enrichment_queue q
  set status = 'error',
      error_kind = nullif(pg_catalog.left(coalesce(p_error_kind, ''), 120), ''),
      last_error = nullif(pg_catalog.left(coalesce(p_last_error, ''), 2000), ''),
      next_retry_at = case
        when q.attempt_count < q.max_attempts then
          clock_timestamp() + pg_catalog.make_interval(
            secs => greatest(30, least(coalesce(p_retry_after_seconds, 300), 21600))
          )
        else null
      end,
      lease_owner = null,
      lease_until = null,
      completed_at = null,
      updated_at = clock_timestamp()
  where q.id = p_id
    and q.status = 'running'
    and q.lease_owner = p_owner
  returning q.attempt_count, q.max_attempts
  into v_attempt_count, v_max_attempts;

  if not found then
    return 'not_owned';
  end if;
  return case when v_attempt_count < v_max_attempts then 'retry' else 'error' end;
end;
$$;

-- Return quota-unclaimed leases to the queue without consuming an attempt.
create or replace function public.twss_release_enrichment(
  p_ids bigint[],
  p_owner text,
  p_retry_after_seconds integer default 300
)
returns integer
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_changed integer := 0;
begin
  if nullif(pg_catalog.btrim(coalesce(p_owner, '')), '') is null then
    raise exception 'enrichment_owner_required' using errcode = '22023';
  end if;

  update public.stock_enrichment_queue q
  set status = 'pending',
      attempt_count = greatest(q.attempt_count - 1, 0),
      next_retry_at = clock_timestamp() + pg_catalog.make_interval(
        secs => greatest(30, least(coalesce(p_retry_after_seconds, 300), 21600))
      ),
      lease_owner = null,
      lease_until = null,
      updated_at = clock_timestamp()
  where q.id = any(coalesce(p_ids, '{}'::bigint[]))
    and q.status = 'running'
    and q.lease_owner = p_owner;

  get diagnostics v_changed = row_count;
  return v_changed;
end;
$$;

revoke all on function public.twss_claim_enrichment_batch(text, integer, integer, text[])
  from public, anon, authenticated;
revoke all on function public.twss_complete_enrichment(bigint, text, date, jsonb)
  from public, anon, authenticated;
revoke all on function public.twss_fail_enrichment(bigint, text, text, text, integer)
  from public, anon, authenticated;
revoke all on function public.twss_release_enrichment(bigint[], text, integer)
  from public, anon, authenticated;

grant execute on function public.twss_claim_enrichment_batch(text, integer, integer, text[])
  to service_role;
grant execute on function public.twss_complete_enrichment(bigint, text, date, jsonb)
  to service_role;
grant execute on function public.twss_fail_enrichment(bigint, text, text, text, integer)
  to service_role;
grant execute on function public.twss_release_enrichment(bigint[], text, integer)
  to service_role;

-- One bounded RPC replaces six per-symbol PostgREST history reads.  Each
-- history is selected newest-first for LIMIT efficiency and returned oldest-
-- first for the existing quantitative analyzers.
create or replace function public.twss_analysis_inputs(
  p_symbols text[],
  p_price_limit integer default 280,
  p_revenue_limit integer default 40,
  p_financial_limit integer default 12,
  p_flow_limit integer default 30
)
returns table (symbol text, payload jsonb)
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
  v_price_limit integer := greatest(1, least(coalesce(p_price_limit, 280), 400));
  v_revenue_limit integer := greatest(1, least(coalesce(p_revenue_limit, 40), 60));
  v_financial_limit integer := greatest(1, least(coalesce(p_financial_limit, 12), 20));
  v_flow_limit integer := greatest(1, least(coalesce(p_flow_limit, 30), 90));
begin
  if coalesce(pg_catalog.cardinality(p_symbols), 0) > 500 then
    raise exception 'analysis_input_symbol_limit_exceeded' using errcode = '22023';
  end if;

  return query
  with requested as (
    select distinct pg_catalog.btrim(requested_symbol) as requested_symbol
    from pg_catalog.unnest(coalesce(p_symbols, '{}'::text[])) as input(requested_symbol)
    where pg_catalog.btrim(requested_symbol) ~ '^[0-9]{4,6}[A-Z]?$'
  )
  select
    r.requested_symbol,
    pg_catalog.jsonb_build_object(
      'price_history', coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(h) order by h.trade_date)
        from (
          select p.trade_date, p.open, p.high, p.low, p.close, p.volume,
            p.trade_value, p.transactions, p.source, p.updated_at
          from public.stock_price_history p
          where p.symbol = r.requested_symbol
          order by p.trade_date desc
          limit v_price_limit
        ) h
      ), '[]'::jsonb),
      'revenues', coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(h) order by h.revenue_period)
        from (
          select p.revenue_period, p.revenue_year, p.revenue_month, p.revenue,
            p.mom, p.yoy, p.available_at, p.source, p.updated_at
          from public.stock_monthly_revenues p
          where p.symbol = r.requested_symbol
          order by p.revenue_period desc
          limit v_revenue_limit
        ) h
      ), '[]'::jsonb),
      'financials', coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(h) order by h.report_date, h.report_period)
        from (
          select p.report_period, p.report_date, p.available_at, p.revenue,
            p.net_income, p.eps, p.gross_margin, p.operating_margin, p.net_margin,
            p.roe, p.operating_cash_flow, p.free_cash_flow, p.cash_conversion,
            p.inventory, p.receivables, p.debt_ratio, p.current_ratio,
            p.interest_coverage, p.non_operating_ratio, p.source, p.updated_at
          from public.stock_quarterly_financials p
          where p.symbol = r.requested_symbol
          order by p.report_date desc, p.report_period desc
          limit v_financial_limit
        ) h
      ), '[]'::jsonb),
      'institutional', coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(h) order by h.trade_date)
        from (
          select p.trade_date, p.foreign_net, p.trust_net, p.dealer_net,
            p.institutional_net, p.volume_intensity, p.source, p.updated_at
          from public.stock_institutional_flows p
          where p.symbol = r.requested_symbol
          order by p.trade_date desc
          limit v_flow_limit
        ) h
      ), '[]'::jsonb),
      'margin', coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(h) order by h.trade_date)
        from (
          select p.trade_date, p.margin_balance, p.margin_limit, p.short_balance,
            p.source, p.updated_at
          from public.stock_margin_history p
          where p.symbol = r.requested_symbol
          order by p.trade_date desc
          limit v_flow_limit
        ) h
      ), '[]'::jsonb),
      'lending', coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(h) order by h.trade_date)
        from (
          select p.trade_date, p.lending_value, p.source, p.raw_data, p.updated_at
          from public.stock_lending_history p
          where p.symbol = r.requested_symbol
          order by p.trade_date desc
          limit v_flow_limit
        ) h
      ), '[]'::jsonb)
    )
  from requested r
  order by r.requested_symbol;
end;
$$;

revoke all on function public.twss_analysis_inputs(text[], integer, integer, integer, integer)
  from public, anon, authenticated;
grant execute on function public.twss_analysis_inputs(text[], integer, integer, integer, integer)
  to service_role;

-- Shared completion summary for the v20 publisher and administrator console.
create or replace function public.twss_enrichment_summary(p_data_date date)
returns jsonb
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
  v_total integer := 0;
  v_pending integer := 0;
  v_running integer := 0;
  v_success integer := 0;
  v_error integer := 0;
  v_retryable integer := 0;
  v_terminal integer := 0;
  v_next_retry_at timestamptz;
  v_by_dataset jsonb := '{}'::jsonb;
begin
  if p_data_date is null then
    raise exception 'enrichment_data_date_required' using errcode = '22023';
  end if;

  select
    count(*)::integer,
    count(*) filter (where q.status = 'pending')::integer,
    count(*) filter (where q.status = 'running')::integer,
    count(*) filter (where q.status = 'success')::integer,
    count(*) filter (where q.status = 'error')::integer,
    count(*) filter (
      where q.status = 'error'
        and q.attempt_count < q.max_attempts
        and q.next_retry_at is not null
    )::integer,
    count(*) filter (
      where q.status = 'error'
        and (q.attempt_count >= q.max_attempts or q.next_retry_at is null)
    )::integer,
    min(q.next_retry_at) filter (
      where q.status in ('pending', 'error') and q.next_retry_at is not null
    )
  into v_total, v_pending, v_running, v_success, v_error,
    v_retryable, v_terminal, v_next_retry_at
  from public.stock_enrichment_queue q
  where q.data_date = p_data_date;

  select coalesce(pg_catalog.jsonb_object_agg(
    grouped.dataset_key,
    pg_catalog.jsonb_build_object(
      'total', grouped.total,
      'pending', grouped.pending,
      'running', grouped.running,
      'success', grouped.success,
      'error', grouped.error,
      'retryableErrors', grouped.retryable_errors,
      'terminalErrors', grouped.terminal_errors
    )
    order by grouped.dataset_key
  ), '{}'::jsonb)
  into v_by_dataset
  from (
    select
      q.dataset_key,
      count(*)::integer as total,
      count(*) filter (where q.status = 'pending')::integer as pending,
      count(*) filter (where q.status = 'running')::integer as running,
      count(*) filter (where q.status = 'success')::integer as success,
      count(*) filter (where q.status = 'error')::integer as error,
      count(*) filter (
        where q.status = 'error' and q.attempt_count < q.max_attempts and q.next_retry_at is not null
      )::integer as retryable_errors,
      count(*) filter (
        where q.status = 'error' and (q.attempt_count >= q.max_attempts or q.next_retry_at is null)
      )::integer as terminal_errors
    from public.stock_enrichment_queue q
    where q.data_date = p_data_date
    group by q.dataset_key
  ) grouped;

  return pg_catalog.jsonb_build_object(
    'dataDate', p_data_date,
    'total', v_total,
    'pending', v_pending,
    'running', v_running,
    'success', v_success,
    'error', v_error,
    'retryableErrors', v_retryable,
    'terminalErrors', v_terminal,
    'unresolved', v_pending + v_running + v_retryable,
    'complete', v_total > 0 and (v_pending + v_running + v_retryable) = 0,
    'nextRetryAt', v_next_retry_at,
    'byDataset', v_by_dataset
  );
end;
$$;

revoke all on function public.twss_enrichment_summary(date)
  from public, anon, authenticated;
grant execute on function public.twss_enrichment_summary(date)
  to service_role;

-- Seed backward-compatible publication metadata inside the existing JSONB
-- state rather than adding mandatory columns to legacy clients.
insert into public.stock_sync_state (job_key, group_name, details)
values (
  'enrichment',
  null,
  '{"publicationPhase":"cached","baseCompletedAt":null,"enrichmentCompletedAt":null,"enrichmentPending":0,"sourceDates":{},"dataCompleteness":0}'::jsonb
)
on conflict (job_key) do update
set details = excluded.details || coalesce(public.stock_sync_state.details, '{}'::jsonb),
    updated_at = clock_timestamp();

update public.stock_sync_state
set details = '{"publicationPhase":"cached","baseCompletedAt":null,"enrichmentCompletedAt":null,"enrichmentPending":0,"sourceDates":{},"dataCompleteness":0}'::jsonb
    || coalesce(details, '{}'::jsonb),
    updated_at = clock_timestamp()
where job_key = 'v20_model';

-- Extend, but do not replace, the existing administrator payload.
do $$
begin
  if pg_catalog.to_regprocedure('public.twss_admin_operations_log_v200(integer)') is null then
    alter function public.twss_admin_operations_log(integer)
      rename to twss_admin_operations_log_v200;
  end if;
end;
$$;

revoke all on function public.twss_admin_operations_log_v200(integer)
  from public, anon, authenticated;
grant execute on function public.twss_admin_operations_log_v200(integer)
  to service_role;

create or replace function public.twss_admin_operations_log(p_limit integer default 60)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  v_limit integer := greatest(1, least(coalesce(p_limit, 60), 100));
  v_payload jsonb;
  v_universe_date date;
  v_enrichment jsonb;
  v_base_analysis jsonb;
  v_publication jsonb;
  v_model_state public.stock_sync_state%rowtype;
begin
  if (select auth.uid()) is null or not (select public.twss_is_admin()) then
    raise exception using errcode = '42501', message = 'admin_required';
  end if;

  v_payload := public.twss_admin_operations_log_v200(v_limit);

  select s.cycle_date
  into v_universe_date
  from public.stock_sync_state s
  where s.job_key = 'universe'
  limit 1;

  v_enrichment := case
    when v_universe_date is null then pg_catalog.jsonb_build_object(
      'dataDate', null, 'total', 0, 'pending', 0, 'running', 0,
      'success', 0, 'error', 0, 'retryableErrors', 0,
      'terminalErrors', 0, 'unresolved', 0, 'complete', false,
      'nextRetryAt', null, 'byDataset', '{}'::jsonb
    )
    else public.twss_enrichment_summary(v_universe_date)
  end;

  select pg_catalog.jsonb_build_object(
    'dataDate', v_universe_date,
    'total', coalesce(sum(s.total_items), 0),
    'processed', coalesce(sum(s.processed_count), 0),
    'ready', count(*) = 3
      and coalesce(sum(s.total_items), 0) > 0
      and coalesce(bool_and(
        s.cycle_date = v_universe_date
        and s.status in ('success', 'partial')
        and s.total_items > 0
        and s.processed_count >= s.total_items
      ), false),
    'groups', coalesce(pg_catalog.jsonb_object_agg(
      s.group_name,
      pg_catalog.jsonb_build_object(
        'jobKey', s.job_key,
        'status', s.status,
        'cycleDate', s.cycle_date,
        'processed', s.processed_count,
        'total', s.total_items,
        'progress', case when s.total_items > 0
          then round(100 * s.processed_count::numeric / s.total_items, 1)
          else 0 end,
        'lastSuccessAt', s.last_success_at,
        'lastError', s.last_error
      ) order by s.group_name
    ), '{}'::jsonb)
  )
  into v_base_analysis
  from public.stock_sync_state s
  where s.job_key in ('deep_listed', 'deep_otc', 'deep_etf');

  select s.* into v_model_state
  from public.stock_sync_state s
  where s.job_key = 'v20_model'
  limit 1;

  v_publication := pg_catalog.jsonb_build_object(
    'publicationPhase', coalesce(v_model_state.details ->> 'publicationPhase', 'cached'),
    'baseCompletedAt', v_model_state.details -> 'baseCompletedAt',
    'enrichmentCompletedAt', v_model_state.details -> 'enrichmentCompletedAt',
    'enrichmentPending', coalesce((v_enrichment ->> 'unresolved')::integer, 0),
    'sourceDates', coalesce(v_model_state.details -> 'sourceDates', '{}'::jsonb),
    'dataCompleteness', coalesce(v_model_state.details -> 'dataCompleteness', '0'::jsonb),
    'modelStatus', v_model_state.status,
    'modelCycleDate', v_model_state.cycle_date
  );

  return v_payload || pg_catalog.jsonb_build_object(
    'enrichmentQueue', v_enrichment,
    'baseAnalysis', v_base_analysis,
    'publication', v_publication,
    'summary', coalesce(v_payload -> 'summary', '{}'::jsonb)
      || pg_catalog.jsonb_build_object(
        'baseAnalysisReady', coalesce((v_base_analysis ->> 'ready')::boolean, false),
        'publicationPhase', v_publication ->> 'publicationPhase',
        'enrichmentPending', coalesce((v_enrichment ->> 'unresolved')::integer, 0),
        'enrichmentErrors', coalesce((v_enrichment ->> 'terminalErrors')::integer, 0)
      )
  );
end;
$$;

revoke all on function public.twss_admin_operations_log(integer)
  from public, anon, authenticated;
grant execute on function public.twss_admin_operations_log(integer)
  to authenticated, service_role;

comment on table public.stock_enrichment_queue is
  'Service-only, idempotent daily FinMind enrichment queue. Base publication never waits on these rows.';
comment on function public.twss_analysis_inputs(text[], integer, integer, integer, integer) is
  'Service-only bounded database-first analysis input aggregator; eliminates per-symbol REST fan-out.';
comment on function public.twss_admin_operations_log(integer) is
  'Intentional SECURITY DEFINER boundary: active administrators only; extends the existing payload with v20 base/publication/enrichment health.';

-- pg_cron uses UTC. 07:00-15:59 is 15:00-23:59 Asia/Taipei.  The three
-- database-only base groups and v20 publisher run on even minutes.  FinMind
-- enrichment runs only on selected odd minutes, keeping the maximum scheduled
-- starts below eight even when the existing v19/news/universe/maintenance jobs
-- share a minute.  Existing 17:10/21:10 universe reconciliation is untouched.
do $$
declare
  existing_job bigint;
begin
  for existing_job in
    select jobid
    from cron.job
    where jobname in (
      'twss-deep-listed',
      'twss-deep-otc',
      'twss-deep-etf',
      'twss-enrichment-weekday',
      'twss-v20-model-weekday',
      'twss-v20-model-weekday-final'
    )
  loop
    perform cron.unschedule(existing_job);
  end loop;
end;
$$;

select cron.schedule(
  'twss-deep-listed',
  '*/2 7-15 * * 1-5',
  $job$
    select net.http_post(
      url := 'https://lfkdkdyaatdlizryiyon.supabase.co/functions/v1/twss-sync-batch',
      headers := jsonb_build_object(
        'Content-Type', 'application/json',
        'x-twss-sync-token', (
          select decrypted_secret from vault.decrypted_secrets where name = 'twss_sync_token'
        )
      ),
      body := '{"mode":"deep","group":"listed","limit":200}'::jsonb,
      timeout_milliseconds := 300000
    );
  $job$
);

select cron.schedule(
  'twss-deep-otc',
  '*/2 7-15 * * 1-5',
  $job$
    select net.http_post(
      url := 'https://lfkdkdyaatdlizryiyon.supabase.co/functions/v1/twss-sync-batch',
      headers := jsonb_build_object(
        'Content-Type', 'application/json',
        'x-twss-sync-token', (
          select decrypted_secret from vault.decrypted_secrets where name = 'twss_sync_token'
        )
      ),
      body := '{"mode":"deep","group":"otc","limit":200}'::jsonb,
      timeout_milliseconds := 300000
    );
  $job$
);

select cron.schedule(
  'twss-deep-etf',
  '*/2 7-15 * * 1-5',
  $job$
    select net.http_post(
      url := 'https://lfkdkdyaatdlizryiyon.supabase.co/functions/v1/twss-sync-batch',
      headers := jsonb_build_object(
        'Content-Type', 'application/json',
        'x-twss-sync-token', (
          select decrypted_secret from vault.decrypted_secrets where name = 'twss_sync_token'
        )
      ),
      body := '{"mode":"deep","group":"etf","limit":200}'::jsonb,
      timeout_milliseconds := 300000
    );
  $job$
);

select cron.schedule(
  'twss-enrichment-weekday',
  '1,5,11,15,21,25,31,35,41,45,51,55 7-15 * * 1-5',
  $job$
    select net.http_post(
      url := 'https://lfkdkdyaatdlizryiyon.supabase.co/functions/v1/twss-sync-batch',
      headers := jsonb_build_object(
        'Content-Type', 'application/json',
        'x-twss-sync-token', (
          select decrypted_secret from vault.decrypted_secrets where name = 'twss_sync_token'
        )
      ),
      body := '{"mode":"enrichment","limit":50}'::jsonb,
      timeout_milliseconds := 300000
    );
  $job$
);

select cron.schedule(
  'twss-v20-model-weekday',
  '*/2 7-15 * * 1-5',
  $job$
    select net.http_post(
      url := 'https://lfkdkdyaatdlizryiyon.supabase.co/functions/v1/twss-v20-model',
      headers := jsonb_build_object(
        'Content-Type', 'application/json',
        'x-twss-sync-token', (
          select decrypted_secret from vault.decrypted_secrets where name = 'twss_sync_token'
        )
      ),
      body := '{"limit":250}'::jsonb,
      timeout_milliseconds := 300000
    );
  $job$
);

-- One final 23:59 Taiwan invocation closes a cycle that finished after 23:58.
select cron.schedule(
  'twss-v20-model-weekday-final',
  '59 15 * * 1-5',
  $job$
    select net.http_post(
      url := 'https://lfkdkdyaatdlizryiyon.supabase.co/functions/v1/twss-v20-model',
      headers := jsonb_build_object(
        'Content-Type', 'application/json',
        'x-twss-sync-token', (
          select decrypted_secret from vault.decrypted_secrets where name = 'twss_sync_token'
        )
      ),
      body := '{"limit":250}'::jsonb,
      timeout_milliseconds := 300000
    );
  $job$
);

begin;

set local search_path = pg_catalog, public, extensions;

create table market_data.historical_backfill_tasks (
  task_id bigint generated always as identity primary key,
  provider_code text not null
    references market_data.data_sources(source_code) on delete restrict,
  source_dataset text not null,
  security_id bigint
    references market_data.securities(security_id) on delete restrict,
  source_symbol text not null,
  display_name text,
  market text not null check (market in ('TWSE', 'TPEX')),
  asset_type text not null check (asset_type in ('COMMON_STOCK', 'ETF')),
  priority smallint generated always as (
    case
      when asset_type = 'COMMON_STOCK' and market = 'TWSE' then 10
      when asset_type = 'COMMON_STOCK' and market = 'TPEX' then 20
      else 30
    end
  ) stored,
  requested_start_date date not null,
  requested_end_date date not null,
  selection_snapshot_at timestamptz not null,
  selection_basis text not null
    default 'CURRENT_SECURITY_MASTER_SCHEDULING_ONLY',
  status text not null default 'PENDING'
    check (status in ('PENDING', 'LEASED', 'RETRY', 'SUCCEEDED', 'EXHAUSTED')),
  attempt_count integer not null default 0,
  max_attempts smallint not null default 5,
  next_attempt_at timestamptz not null default now(),
  lease_token uuid,
  claimed_by text,
  lease_expires_at timestamptz,
  latest_completed_trade_date date,
  fetched_rows integer not null default 0,
  landed_rows integer not null default 0,
  quarantined_rows integer not null default 0,
  quarantine_issues integer not null default 0,
  last_result_code text,
  last_error_code text,
  completed_at timestamptz,
  usage_scope text not null default 'RAW_LANDING_ONLY',
  system_status text not null default 'RESEARCH_ONLY',
  reason_codes text[] not null default array[
    'REQUEST_UNIVERSE_NOT_POINT_IN_TIME',
    'HISTORICAL_VINTAGE_UNAVAILABLE',
    'IDENTITY_UNRESOLVED',
    'RAW_LANDING_ONLY'
  ],
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (
    provider_code,
    source_dataset,
    market,
    source_symbol,
    requested_start_date,
    requested_end_date
  ),
  constraint historical_backfill_task_identity_check check (
    nullif(btrim(source_dataset), '') is not null
    and nullif(btrim(source_symbol), '') is not null
    and length(source_symbol) <= 32
    and (
      (asset_type = 'COMMON_STOCK' and security_id is not null)
      or asset_type = 'ETF'
    )
  ),
  constraint historical_backfill_task_range_check check (
    requested_start_date <= requested_end_date
    and (
      latest_completed_trade_date is null
      or latest_completed_trade_date between requested_start_date and requested_end_date
    )
  ),
  constraint historical_backfill_task_attempt_check check (
    max_attempts between 1 and 20
    and attempt_count between 0 and max_attempts
    and fetched_rows >= 0
    and landed_rows >= 0
    and quarantined_rows >= 0
    and quarantine_issues >= 0
  ),
  constraint historical_backfill_task_research_scope_check check (
    selection_basis = 'CURRENT_SECURITY_MASTER_SCHEDULING_ONLY'
    and usage_scope = 'RAW_LANDING_ONLY'
    and system_status = 'RESEARCH_ONLY'
    and 'REQUEST_UNIVERSE_NOT_POINT_IN_TIME' = any(reason_codes)
  ),
  constraint historical_backfill_task_state_check check (
    (
      status = 'LEASED'
      and lease_token is not null
      and nullif(btrim(claimed_by), '') is not null
      and lease_expires_at is not null
      and completed_at is null
    )
    or (
      status in ('PENDING', 'RETRY')
      and lease_token is null
      and claimed_by is null
      and lease_expires_at is null
      and completed_at is null
    )
    or (
      status in ('SUCCEEDED', 'EXHAUSTED')
      and lease_token is null
      and claimed_by is null
      and lease_expires_at is null
      and completed_at is not null
    )
  )
);

create index historical_backfill_tasks_claim_idx
  on market_data.historical_backfill_tasks (
    provider_code,
    status,
    next_attempt_at,
    priority,
    requested_start_date,
    task_id
  )
  where status in ('PENDING', 'RETRY', 'LEASED');

create index historical_backfill_tasks_progress_idx
  on market_data.historical_backfill_tasks (
    requested_start_date,
    requested_end_date,
    priority,
    status
  );

create index historical_backfill_tasks_security_id_idx
  on market_data.historical_backfill_tasks (security_id)
  where security_id is not null;

comment on table market_data.historical_backfill_tasks is
  'Service-role-only resumable queue for research-only historical landing imports.';
comment on column market_data.historical_backfill_tasks.priority is
  'Strict scheduling order: TWSE common stock, TPEX common stock, then ETF.';
comment on column market_data.historical_backfill_tasks.selection_basis is
  'Scheduling aid only; never evidence of historical point-in-time membership.';

alter table market_data.historical_backfill_tasks enable row level security;

revoke all on market_data.historical_backfill_tasks
  from public, anon, authenticated;
revoke all on sequence market_data.historical_backfill_tasks_task_id_seq
  from public, anon, authenticated;
revoke delete on market_data.historical_backfill_tasks from service_role;

grant select, insert, update
  on market_data.historical_backfill_tasks to service_role;
grant usage, select
  on sequence market_data.historical_backfill_tasks_task_id_seq to service_role;

create or replace function market_data.seed_historical_backfill_common_tasks(
  p_start_date date,
  p_end_date date,
  p_selection_snapshot_at timestamptz
)
returns integer
language plpgsql
security invoker
set search_path = pg_catalog, market_data
as $function$
declare
  inserted_count integer;
begin
  if p_start_date is null
     or p_end_date is null
     or p_selection_snapshot_at is null
     or p_start_date > p_end_date then
    raise exception using
      errcode = '22023',
      message = 'valid start, end and selection snapshot are required';
  end if;

  with candidates as materialized (
    select
      security.security_id,
      security.symbol,
      security.display_name,
      security.market,
      greatest(
        p_start_date,
        coalesce(security.listing_date, p_start_date)
      ) as range_start,
      least(
        p_end_date,
        coalesce(security.delisting_date, p_end_date)
      ) as range_end
    from market_data.securities as security
    where security.asset_type = 'COMMON_STOCK'
  ), coverage as materialized (
    select
      candidate.*,
      min(landing.trade_date) filter (
        where landing.parse_status = 'PARSED'
      ) as earliest_trade_date,
      max(landing.trade_date) filter (
        where landing.parse_status = 'PARSED'
      ) as latest_trade_date
    from candidates as candidate
    left join market_data.historical_daily_bar_landing as landing
      on landing.source_symbol = candidate.symbol
     and landing.source_dataset = 'daily_bars'
     and landing.source_id = (
       select source_id
       from market_data.data_sources
       where source_code = 'FINMIND'
     )
     and landing.trade_date between candidate.range_start and candidate.range_end
    where candidate.range_start <= candidate.range_end
    group by
      candidate.security_id,
      candidate.symbol,
      candidate.display_name,
      candidate.market,
      candidate.range_start,
      candidate.range_end
  )
  insert into market_data.historical_backfill_tasks (
    provider_code,
    source_dataset,
    security_id,
    source_symbol,
    display_name,
    market,
    asset_type,
    requested_start_date,
    requested_end_date,
    selection_snapshot_at,
    status,
    latest_completed_trade_date,
    completed_at,
    last_result_code
  )
  select
    'FINMIND',
    'daily_bars',
    coverage.security_id,
    coverage.symbol,
    coverage.display_name,
    coverage.market,
    'COMMON_STOCK',
    coverage.range_start,
    coverage.range_end,
    p_selection_snapshot_at,
    case
      when coverage.earliest_trade_date <= coverage.range_start
       and coverage.latest_trade_date >= coverage.range_end then 'SUCCEEDED'
      else 'PENDING'
    end,
    coverage.latest_trade_date,
    case
      when coverage.earliest_trade_date <= coverage.range_start
       and coverage.latest_trade_date >= coverage.range_end then now()
      else null
    end,
    case
      when coverage.earliest_trade_date <= coverage.range_start
       and coverage.latest_trade_date >= coverage.range_end
        then 'PREEXISTING_LANDING_COVERAGE'
      else null
    end
  from coverage
  on conflict (
    provider_code,
    source_dataset,
    market,
    source_symbol,
    requested_start_date,
    requested_end_date
  ) do nothing;

  get diagnostics inserted_count = row_count;
  return inserted_count;
end
$function$;

create or replace function market_data.claim_historical_backfill_tasks(
  p_provider_code text,
  p_worker_id text,
  p_claim_token uuid,
  p_limit integer default 1,
  p_lease_seconds integer default 1800
)
returns setof market_data.historical_backfill_tasks
language plpgsql
security invoker
set search_path = pg_catalog, market_data
as $function$
begin
  if nullif(btrim(p_provider_code), '') is null
     or nullif(btrim(p_worker_id), '') is null
     or p_claim_token is null then
    raise exception using
      errcode = '22023',
      message = 'provider, worker and claim token are required';
  end if;
  if p_limit is null
     or p_lease_seconds is null
     or p_limit not between 1 and 100
     or p_lease_seconds not between 60 and 3600 then
    raise exception using
      errcode = '22023',
      message = 'claim limit or lease duration is outside allowed bounds';
  end if;

  update market_data.historical_backfill_tasks
  set
    status = 'EXHAUSTED',
    lease_token = null,
    claimed_by = null,
    lease_expires_at = null,
    completed_at = now(),
    last_error_code = 'LEASE_EXPIRED_AT_MAX_ATTEMPTS',
    updated_at = now()
  where status = 'LEASED'
    and lease_expires_at <= now()
    and attempt_count >= max_attempts;

  return query
  with active_priority as materialized (
    select min(priority) as priority
    from market_data.historical_backfill_tasks
    where provider_code = p_provider_code
      and status in ('PENDING', 'LEASED', 'RETRY')
  ), candidates as materialized (
    select task_id
    from market_data.historical_backfill_tasks
    cross join active_priority
    where provider_code = p_provider_code
      and historical_backfill_tasks.priority = active_priority.priority
      and attempt_count < max_attempts
      and (
        (status in ('PENDING', 'RETRY') and next_attempt_at <= now())
        or (status = 'LEASED' and lease_expires_at <= now())
      )
    order by priority, requested_start_date, market, source_symbol, task_id
    for update skip locked
    limit p_limit
  )
  update market_data.historical_backfill_tasks as task
  set
    status = 'LEASED',
    attempt_count = task.attempt_count + 1,
    lease_token = p_claim_token,
    claimed_by = p_worker_id,
    lease_expires_at = now() + make_interval(secs => p_lease_seconds),
    completed_at = null,
    updated_at = now()
  from candidates
  where task.task_id = candidates.task_id
  returning task.*;
end
$function$;

create or replace function market_data.complete_historical_backfill_task(
  p_task_id bigint,
  p_claim_token uuid,
  p_success boolean,
  p_latest_completed_trade_date date default null,
  p_fetched_rows integer default 0,
  p_landed_rows integer default 0,
  p_quarantined_rows integer default 0,
  p_quarantine_issues integer default 0,
  p_retry_after_seconds integer default 900,
  p_error_code text default null
)
returns boolean
language plpgsql
security invoker
set search_path = pg_catalog, market_data
as $function$
declare
  updated_task_id bigint;
begin
  if p_task_id is null
     or p_claim_token is null
     or p_success is null
     or p_fetched_rows is null
     or p_landed_rows is null
     or p_quarantined_rows is null
     or p_quarantine_issues is null
     or p_retry_after_seconds is null
     or p_retry_after_seconds not between 60 and 86400
     or least(
       p_fetched_rows,
       p_landed_rows,
       p_quarantined_rows,
       p_quarantine_issues
     ) < 0 then
    raise exception using
      errcode = '22023',
      message = 'invalid completion arguments';
  end if;
  if p_success and p_latest_completed_trade_date is null then
    raise exception using
      errcode = '22023',
      message = 'successful completion requires latest trade date';
  end if;

  update market_data.historical_backfill_tasks as task
  set
    status = case
      when p_success then 'SUCCEEDED'
      when task.attempt_count >= task.max_attempts then 'EXHAUSTED'
      else 'RETRY'
    end,
    next_attempt_at = case
      when not p_success and task.attempt_count < task.max_attempts
        then now() + make_interval(secs => p_retry_after_seconds)
      else task.next_attempt_at
    end,
    latest_completed_trade_date = case
      when p_success then p_latest_completed_trade_date
      else task.latest_completed_trade_date
    end,
    fetched_rows = p_fetched_rows,
    landed_rows = p_landed_rows,
    quarantined_rows = p_quarantined_rows,
    quarantine_issues = p_quarantine_issues,
    last_result_code = case
      when p_success and p_quarantined_rows > 0 then 'COMPLETED_WITH_QUARANTINE'
      when p_success then 'COMPLETED'
      else null
    end,
    last_error_code = case
      when p_success then null
      else coalesce(nullif(btrim(p_error_code), ''), 'UNKNOWN_IMPORT_ERROR')
    end,
    completed_at = case
      when p_success or task.attempt_count >= task.max_attempts then now()
      else null
    end,
    lease_token = null,
    claimed_by = null,
    lease_expires_at = null,
    updated_at = now()
  where task.task_id = p_task_id
    and task.status = 'LEASED'
    and task.lease_token = p_claim_token
    and task.lease_expires_at > now()
  returning task.task_id into updated_task_id;

  return updated_task_id is not null;
end
$function$;

create or replace function market_data.historical_backfill_snapshot(
  p_start_date date,
  p_end_date date
)
returns table (
  database_bytes bigint,
  landing_bytes bigint,
  landing_symbols bigint,
  task_count bigint,
  twse_common_remaining bigint,
  tpex_common_remaining bigint,
  etf_task_count bigint,
  etf_remaining bigint,
  succeeded bigint,
  exhausted bigint
)
language sql
stable
security invoker
set search_path = pg_catalog, market_data
as $function$
  select
    pg_database_size(current_database()),
    pg_total_relation_size('market_data.historical_daily_bar_landing'),
    (
      select count(distinct source_symbol)
      from market_data.historical_daily_bar_landing
    ),
    count(*),
    count(*) filter (
      where asset_type = 'COMMON_STOCK'
        and market = 'TWSE'
        and status in ('PENDING', 'LEASED', 'RETRY')
    ),
    count(*) filter (
      where asset_type = 'COMMON_STOCK'
        and market = 'TPEX'
        and status in ('PENDING', 'LEASED', 'RETRY')
    ),
    count(*) filter (where asset_type = 'ETF'),
    count(*) filter (
      where asset_type = 'ETF'
        and status in ('PENDING', 'LEASED', 'RETRY')
    ),
    count(*) filter (where status = 'SUCCEEDED'),
    count(*) filter (where status = 'EXHAUSTED')
  from market_data.historical_backfill_tasks
  where requested_start_date >= p_start_date
    and requested_end_date <= p_end_date;
$function$;

revoke all on function market_data.seed_historical_backfill_common_tasks(
  date,
  date,
  timestamptz
) from public, anon, authenticated;
revoke all on function market_data.claim_historical_backfill_tasks(
  text,
  text,
  uuid,
  integer,
  integer
) from public, anon, authenticated;
revoke all on function market_data.complete_historical_backfill_task(
  bigint,
  uuid,
  boolean,
  date,
  integer,
  integer,
  integer,
  integer,
  integer,
  text
) from public, anon, authenticated;
revoke all on function market_data.historical_backfill_snapshot(date, date)
  from public, anon, authenticated;

grant execute on function market_data.seed_historical_backfill_common_tasks(
  date,
  date,
  timestamptz
) to service_role;
grant execute on function market_data.claim_historical_backfill_tasks(
  text,
  text,
  uuid,
  integer,
  integer
) to service_role;
grant execute on function market_data.complete_historical_backfill_task(
  bigint,
  uuid,
  boolean,
  date,
  integer,
  integer,
  integer,
  integer,
  integer,
  text
) to service_role;
grant execute on function market_data.historical_backfill_snapshot(date, date)
  to service_role;

commit;

notify pgrst, 'reload schema';

begin;

set local lock_timeout = '5s';
set local statement_timeout = '60s';

create table market_data.prediction_snapshot_rate_limits (
  rate_limit_key_sha256 text primary key,
  window_started_at timestamptz not null,
  request_count integer not null,
  updated_at timestamptz not null default transaction_timestamp(),
  constraint prediction_snapshot_rate_limit_key_sha256_check
    check (rate_limit_key_sha256 ~ '^[0-9a-f]{64}$'),
  constraint prediction_snapshot_rate_limit_request_count_check
    check (request_count >= 1)
);

comment on table market_data.prediction_snapshot_rate_limits is
  'Opaque HMAC client keys and fixed-window counters for the public prediction snapshot endpoint.';
comment on column market_data.prediction_snapshot_rate_limits.rate_limit_key_sha256 is
  'HMAC-SHA256 client key. Raw client addresses must never be persisted.';

create index prediction_snapshot_rate_limits_updated_at_idx
  on market_data.prediction_snapshot_rate_limits (updated_at);

alter table market_data.prediction_snapshot_rate_limits enable row level security;
alter table market_data.prediction_snapshot_rate_limits force row level security;

revoke all on table market_data.prediction_snapshot_rate_limits
  from public, anon, authenticated;
grant select, insert, update, delete
  on table market_data.prediction_snapshot_rate_limits
  to service_role;

create or replace function market_data.consume_prediction_snapshot_rate_limit(
  p_key_sha256 text,
  p_window_seconds integer,
  p_max_requests integer
)
returns table (
  allowed boolean,
  remaining integer,
  retry_after_seconds integer
)
language plpgsql
security invoker
set search_path = pg_catalog, market_data
as $function$
declare
  v_now timestamptz := clock_timestamp();
  v_row market_data.prediction_snapshot_rate_limits%rowtype;
  v_window interval;
begin
  if p_key_sha256 is null
     or p_key_sha256 !~ '^[0-9a-f]{64}$' then
    raise exception using
      errcode = '22023',
      message = 'PREDICTION_RATE_LIMIT_KEY_INVALID';
  end if;
  if p_window_seconds is null
     or p_window_seconds < 1
     or p_window_seconds > 3600 then
    raise exception using
      errcode = '22023',
      message = 'PREDICTION_RATE_LIMIT_WINDOW_INVALID';
  end if;
  if p_max_requests is null
     or p_max_requests < 1
     or p_max_requests > 10000 then
    raise exception using
      errcode = '22023',
      message = 'PREDICTION_RATE_LIMIT_MAX_REQUESTS_INVALID';
  end if;

  v_window := p_window_seconds * interval '1 second';

  insert into market_data.prediction_snapshot_rate_limits as current_window (
    rate_limit_key_sha256,
    window_started_at,
    request_count,
    updated_at
  )
  values (
    p_key_sha256,
    v_now,
    1,
    v_now
  )
  on conflict (rate_limit_key_sha256) do update
  set
    window_started_at = case
      when v_now >= current_window.window_started_at + v_window
        then v_now
      else current_window.window_started_at
    end,
    request_count = case
      when v_now >= current_window.window_started_at + v_window
        then 1
      else least(current_window.request_count + 1, p_max_requests + 1)
    end,
    updated_at = v_now
  returning * into v_row;

  allowed := v_row.request_count <= p_max_requests;
  remaining := greatest(p_max_requests - v_row.request_count, 0);
  retry_after_seconds := case
    when allowed then 0
    else greatest(
      1,
      ceil(
        extract(
          epoch from (v_row.window_started_at + v_window - v_now)
        )
      )::integer
    )
  end;
  return next;
end;
$function$;

revoke all on function market_data.consume_prediction_snapshot_rate_limit(
  text,
  integer,
  integer
) from public, anon, authenticated;
grant execute on function market_data.consume_prediction_snapshot_rate_limit(
  text,
  integer,
  integer
) to service_role;

commit;

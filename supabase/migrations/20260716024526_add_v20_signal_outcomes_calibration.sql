-- Taiwan Stock Smart v20: post-publication outcome tracking and gradual
-- calibration. This migration is additive: it does not rename, move, or
-- rewrite any existing market, signal, backtest, or calibration data.

create table if not exists public.v20_signal_outcomes (
  symbol text not null,
  signal_date date not null,
  model_key text not null check (model_key in ('short', 'medium')),
  horizon_days integer not null,
  model_version text not null default '20.0',
  strategy_key text not null,
  market_regime text not null,
  score_decile smallint not null check (score_decile between 0 and 9),
  opportunity_score numeric not null check (opportunity_score between 0 and 100),
  risk_score numeric not null check (risk_score between 0 and 100),
  confidence numeric not null default 0 check (confidence between 0 and 100),
  up_probability numeric check (up_probability between 0 and 100),
  expected_return_net numeric,
  entry_date date not null,
  entry_open numeric not null check (entry_open > 0),
  horizon_exit_date date not null,
  horizon_close numeric not null check (horizon_close > 0),
  gross_return numeric not null,
  net_return numeric not null,
  mfe numeric not null,
  mae numeric not null,
  stop_loss numeric check (stop_loss > 0),
  take_profit_1 numeric check (take_profit_1 > 0),
  plan_exit_date date not null,
  plan_exit_price numeric not null check (plan_exit_price > 0),
  plan_exit_reason text not null check (
    plan_exit_reason in ('horizon_close', 'stop', 'stop_first_same_bar', 'target')
  ),
  plan_gross_return numeric not null,
  plan_net_return numeric not null,
  stop_hit_first boolean,
  target_hit_first boolean,
  buy_commission_rate numeric not null check (buy_commission_rate between 0 and 0.05),
  sell_commission_rate numeric not null check (sell_commission_rate between 0 and 0.05),
  sell_tax_rate numeric not null check (sell_tax_rate between 0 and 0.05),
  slippage_rate_per_side numeric not null check (slippage_rate_per_side between 0 and 0.05),
  spread_rate_per_side numeric not null check (spread_rate_per_side between 0 and 0.05),
  transaction_cost_pct numeric not null check (transaction_cost_pct >= 0),
  slippage_cost_pct numeric not null check (slippage_cost_pct >= 0),
  spread_cost_pct numeric not null check (spread_cost_pct >= 0),
  total_cost_pct numeric not null check (total_cost_pct >= 0),
  evaluated_as_of date not null,
  evaluated_at timestamptz not null default clock_timestamp(),
  updated_at timestamptz not null default clock_timestamp(),
  primary key (symbol, signal_date, model_key, horizon_days, model_version),
  foreign key (symbol, signal_date, model_key, horizon_days, model_version)
    references public.v20_model_signals(symbol, signal_date, model_key, horizon_days, model_version)
    on delete cascade,
  check (
    (model_key = 'short' and horizon_days in (2, 3, 5, 10))
    or (model_key = 'medium' and horizon_days in (20, 40, 60))
  ),
  check (signal_date < entry_date),
  check (entry_date <= horizon_exit_date),
  check (plan_exit_date between entry_date and horizon_exit_date),
  check (horizon_exit_date <= evaluated_as_of),
  check (
    (stop_hit_first is null and target_hit_first is null and plan_exit_reason = 'horizon_close')
    or (stop_hit_first is true and target_hit_first is false and plan_exit_reason in ('stop', 'stop_first_same_bar'))
    or (stop_hit_first is false and target_hit_first is true and plan_exit_reason = 'target')
  )
);

create index if not exists v20_signal_outcomes_calibration_idx
  on public.v20_signal_outcomes
    (model_version, horizon_exit_date, model_key, horizon_days, market_regime, strategy_key, score_decile)
  include (signal_date, net_return, mfe, mae, up_probability, target_hit_first);

create index if not exists v20_signal_outcomes_as_of_idx
  on public.v20_signal_outcomes (model_version, evaluated_as_of desc, signal_date, symbol);

-- Server-only table: RLS is enabled without client policies, and table
-- privileges are explicitly denied to public API roles. Supabase service_role
-- retains only the DML privileges needed by the SECURITY INVOKER RPCs below.
alter table public.v20_signal_outcomes enable row level security;

revoke all on table public.v20_signal_outcomes from public, anon, authenticated, service_role;
grant select, insert, update on table public.v20_signal_outcomes to service_role;

drop trigger if exists v20_signal_outcomes_set_updated_at on public.v20_signal_outcomes;
create trigger v20_signal_outcomes_set_updated_at
before update on public.v20_signal_outcomes
for each row execute function public.set_updated_at();

-- Build both calibration levels consumed by the v20 model:
--   1) exact strategy + regime + opportunity-score decile
--   2) model-wide "all" + regime fallback
-- Only outcomes whose complete horizon is at or before p_as_of_date are used.
create or replace function public.twss_v20_refresh_signal_calibration(
  p_as_of_date date,
  p_model_version text default '20.0'
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_bucket_rows integer := 0;
begin
  if p_as_of_date is null
    or nullif(pg_catalog.btrim(coalesce(p_model_version, '')), '') is null
  then
    raise exception 'v20_invalid_calibration_cycle';
  end if;

  if p_as_of_date > (pg_catalog.clock_timestamp() at time zone 'Asia/Taipei')::date then
    raise exception 'v20_future_as_of_date';
  end if;

  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(
      'twss-v20-signal-calibration:' || p_model_version || ':' || p_as_of_date::text,
      0
    )
  );

  with eligible as materialized (
    select o.*
    from public.v20_signal_outcomes o
    where o.model_version = p_model_version
      and o.horizon_exit_date <= p_as_of_date
      and o.evaluated_as_of <= p_as_of_date
  ), expanded as (
    select
      e.model_key,
      e.model_version,
      e.strategy_key as bucket_strategy_key,
      e.horizon_days,
      e.market_regime,
      e.score_decile as bucket_score_decile,
      e.signal_date,
      e.net_return,
      e.mfe,
      e.mae,
      e.up_probability,
      e.target_hit_first
    from eligible e

    union all

    select
      e.model_key,
      e.model_version,
      'all'::text as bucket_strategy_key,
      e.horizon_days,
      e.market_regime,
      (-1)::smallint as bucket_score_decile,
      e.signal_date,
      e.net_return,
      e.mfe,
      e.mae,
      e.up_probability,
      e.target_hit_first
    from eligible e
  ), aggregated as (
    select
      x.model_key,
      x.model_version,
      x.bucket_strategy_key as strategy_key,
      x.horizon_days,
      x.market_regime,
      x.bucket_score_decile as score_decile,
      pg_catalog.count(*)::integer as sample_count,
      pg_catalog.count(*) filter (where x.net_return > 0)::integer as wins,
      pg_catalog.round(
        100 * pg_catalog.count(*) filter (where x.net_return > 0)::numeric
          / nullif(pg_catalog.count(*), 0),
        4
      ) as raw_probability,
      pg_catalog.round(
        100 * (
          (pg_catalog.count(*) filter (where x.net_return > 0))::numeric + 2
        ) / (pg_catalog.count(*)::numeric + 4),
        4
      ) as calibrated_probability,
      pg_catalog.round(pg_catalog.avg(x.net_return)::numeric, 4) as average_net_return,
      pg_catalog.round(
        (pg_catalog.percentile_cont(0.10) within group (order by x.net_return))::numeric,
        4
      ) as return_p10,
      pg_catalog.round(
        (pg_catalog.percentile_cont(0.50) within group (order by x.net_return))::numeric,
        4
      ) as return_p50,
      pg_catalog.round(
        (pg_catalog.percentile_cont(0.90) within group (order by x.net_return))::numeric,
        4
      ) as return_p90,
      pg_catalog.round(pg_catalog.avg(x.mfe)::numeric, 4) as average_mfe,
      pg_catalog.round(pg_catalog.avg(x.mae)::numeric, 4) as average_mae,
      pg_catalog.round(
        100 * pg_catalog.avg(
          case when x.target_hit_first then 1.0 else 0.0 end
        ) filter (where x.target_hit_first is not null),
        4
      ) as target_first_probability,
      pg_catalog.round(
        100 * pg_catalog.avg(
          pg_catalog.abs(
            x.up_probability / 100
              - case when x.net_return > 0 then 1 else 0 end
          )
        ) filter (where x.up_probability is not null),
        4
      ) as calibration_error,
      pg_catalog.min(x.signal_date) as training_start,
      pg_catalog.max(x.signal_date) as training_end
    from expanded x
    group by
      x.model_key,
      x.model_version,
      x.bucket_strategy_key,
      x.horizon_days,
      x.market_regime,
      x.bucket_score_decile
  )
  insert into public.v20_calibration_buckets (
    model_key,
    model_version,
    strategy_key,
    horizon_days,
    market_regime,
    score_decile,
    sample_count,
    wins,
    raw_probability,
    calibrated_probability,
    average_net_return,
    return_p10,
    return_p50,
    return_p90,
    average_mfe,
    average_mae,
    target_first_probability,
    calibration_error,
    training_start,
    training_end,
    calibration_date,
    generated_at,
    updated_at
  )
  select
    a.model_key,
    a.model_version,
    a.strategy_key,
    a.horizon_days,
    a.market_regime,
    a.score_decile,
    a.sample_count,
    a.wins,
    a.raw_probability,
    a.calibrated_probability,
    a.average_net_return,
    a.return_p10,
    a.return_p50,
    a.return_p90,
    a.average_mfe,
    a.average_mae,
    a.target_first_probability,
    a.calibration_error,
    a.training_start,
    a.training_end,
    p_as_of_date,
    pg_catalog.clock_timestamp(),
    pg_catalog.clock_timestamp()
  from aggregated a
  on conflict (model_key, model_version, strategy_key, horizon_days, market_regime, score_decile)
  do update set
    sample_count = excluded.sample_count,
    wins = excluded.wins,
    raw_probability = excluded.raw_probability,
    calibrated_probability = excluded.calibrated_probability,
    average_net_return = excluded.average_net_return,
    return_p10 = excluded.return_p10,
    return_p50 = excluded.return_p50,
    return_p90 = excluded.return_p90,
    average_mfe = excluded.average_mfe,
    average_mae = excluded.average_mae,
    target_first_probability = excluded.target_first_probability,
    calibration_error = excluded.calibration_error,
    training_start = excluded.training_start,
    training_end = excluded.training_end,
    calibration_date = excluded.calibration_date,
    generated_at = excluded.generated_at,
    updated_at = excluded.updated_at
  where excluded.calibration_date >= public.v20_calibration_buckets.calibration_date;

  get diagnostics v_bucket_rows = row_count;

  return pg_catalog.jsonb_build_object(
    'asOfDate', p_as_of_date,
    'modelVersion', p_model_version,
    'bucketRows', v_bucket_rows,
    'generatedAt', pg_catalog.clock_timestamp()
  );
end;
$$;

revoke all on function public.twss_v20_refresh_signal_calibration(date, text)
  from public, anon, authenticated;
grant execute on function public.twss_v20_refresh_signal_calibration(date, text)
  to service_role;

-- Evaluate a bounded number of mature, published official signals. A signal
-- enters at the next available trading session's open and exits for horizon
-- calibration at the Nth session's close. Its trade-plan outcome is tracked
-- separately; when stop and target occur on one OHLC bar, the stop is applied
-- first. Every source OHLC row is constrained to p_as_of_date or earlier.
create or replace function public.twss_v20_evaluate_signal_outcomes(
  p_as_of_date date default ((pg_catalog.clock_timestamp() at time zone 'Asia/Taipei')::date),
  p_model_version text default '20.0',
  p_model_key text default null,
  p_limit integer default 200,
  p_buy_commission_rate numeric default 0.001425,
  p_sell_commission_rate numeric default 0.001425,
  p_stock_sell_tax_rate numeric default 0.003,
  p_etf_sell_tax_rate numeric default 0.001,
  p_slippage_rate_per_side numeric default 0.001,
  p_spread_rate_per_side numeric default 0.0005
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_evaluated_rows integer := 0;
  v_calibration jsonb := '{}'::jsonb;
begin
  if p_as_of_date is null
    or nullif(pg_catalog.btrim(coalesce(p_model_version, '')), '') is null
    or (p_model_key is not null and p_model_key not in ('short', 'medium'))
    or p_limit is null
    or p_limit < 1
    or p_limit > 500
  then
    raise exception 'v20_invalid_outcome_cycle';
  end if;

  if p_as_of_date > (pg_catalog.clock_timestamp() at time zone 'Asia/Taipei')::date then
    raise exception 'v20_future_as_of_date';
  end if;

  if p_buy_commission_rate is null
    or p_sell_commission_rate is null
    or p_stock_sell_tax_rate is null
    or p_etf_sell_tax_rate is null
    or p_slippage_rate_per_side is null
    or p_spread_rate_per_side is null
    or p_buy_commission_rate not between 0 and 0.05
    or p_sell_commission_rate not between 0 and 0.05
    or p_stock_sell_tax_rate not between 0 and 0.05
    or p_etf_sell_tax_rate not between 0 and 0.05
    or p_slippage_rate_per_side not between 0 and 0.05
    or p_spread_rate_per_side not between 0 and 0.05
  then
    raise exception 'v20_invalid_execution_cost';
  end if;

  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(
      'twss-v20-signal-outcomes:' || p_model_version || ':'
        || coalesce(p_model_key, 'all') || ':' || p_as_of_date::text,
      0
    )
  );

  with mature as materialized (
    select
      s.symbol,
      s.signal_date,
      s.model_key,
      s.horizon_days,
      s.model_version,
      s.strategy_key,
      coalesce(mc.regime, 'sideways') as market_regime,
      least(
        9,
        greatest(0, pg_catalog.floor(s.opportunity_score / 10)::integer)
      )::smallint as score_decile,
      s.opportunity_score,
      s.risk_score,
      s.confidence,
      s.up_probability,
      s.expected_return_net,
      s.stop_loss,
      s.take_profit_1,
      s.group_name,
      path.entry_date,
      path.entry_open,
      path.horizon_exit_date,
      path.horizon_close,
      path.path_high,
      path.path_low
    from public.v20_model_signals s
    left join lateral (
      select c.regime
      from public.v20_market_context c
      where c.model_version = s.model_version
        and c.data_date <= s.signal_date
      order by c.data_date desc
      limit 1
    ) mc on true
    cross join lateral (
      select
        pg_catalog.count(*)::integer as session_count,
        (pg_catalog.array_agg(p.trade_date order by p.trade_date))[1] as entry_date,
        (pg_catalog.array_agg(p.open order by p.trade_date))[1] as entry_open,
        (pg_catalog.array_agg(p.trade_date order by p.trade_date))[s.horizon_days] as horizon_exit_date,
        (pg_catalog.array_agg(p.close order by p.trade_date))[s.horizon_days] as horizon_close,
        pg_catalog.max(p.high) as path_high,
        pg_catalog.min(p.low) as path_low,
        pg_catalog.bool_and(
          p.open is not null and p.open > 0
          and p.high is not null and p.high > 0
          and p.low is not null and p.low > 0
          and p.close is not null and p.close > 0
          and p.high >= greatest(p.open, p.close, p.low)
          and p.low <= least(p.open, p.close, p.high)
        ) as path_complete
      from (
        select ss.trade_date, ss.open, ss.high, ss.low, ss.close
        from public.stock_snapshots ss
        where ss.symbol = s.symbol
          and ss.trade_date > s.signal_date
          and ss.trade_date <= p_as_of_date
        order by ss.trade_date
        limit s.horizon_days
      ) p
    ) path
    where s.model_version = p_model_version
      and (p_model_key is null or s.model_key = p_model_key)
      and s.official
      and s.gate_passed
      and s.signal_date < p_as_of_date
      and path.session_count = s.horizon_days
      and path.path_complete
      and path.entry_date > s.signal_date
      and path.horizon_exit_date <= p_as_of_date
      and not exists (
        select 1
        from public.v20_signal_outcomes existing
        where existing.symbol = s.symbol
          and existing.signal_date = s.signal_date
          and existing.model_key = s.model_key
          and existing.horizon_days = s.horizon_days
          and existing.model_version = s.model_version
      )
    order by s.signal_date, s.symbol, s.model_key, s.horizon_days
    limit p_limit
  ), evaluated as (
    select
      m.*,
      event.event_date,
      event.event_price,
      event.event_reason,
      case
        when event.event_reason = 'target' then true
        when event.event_reason in ('stop', 'stop_first_same_bar') then false
        else null
      end as target_hit_first,
      case
        when event.event_reason = 'target' then false
        when event.event_reason in ('stop', 'stop_first_same_bar') then true
        else null
      end as stop_hit_first,
      case when m.group_name = 'etf' then p_etf_sell_tax_rate else p_stock_sell_tax_rate end
        as applied_sell_tax_rate
    from mature m
    left join lateral (
      select
        e.trade_date as event_date,
        case
          when m.stop_loss is not null and e.low <= m.stop_loss
            then case when e.open < m.stop_loss then e.open else m.stop_loss end
          else m.take_profit_1
        end as event_price,
        case
          when m.stop_loss is not null and e.low <= m.stop_loss
            and m.take_profit_1 is not null and e.high >= m.take_profit_1
            then 'stop_first_same_bar'::text
          when m.stop_loss is not null and e.low <= m.stop_loss
            then 'stop'::text
          else 'target'::text
        end as event_reason
      from (
        select ss.trade_date, ss.open, ss.high, ss.low
        from public.stock_snapshots ss
        where ss.symbol = m.symbol
          and ss.trade_date > m.signal_date
          and ss.trade_date <= m.horizon_exit_date
        order by ss.trade_date
        limit m.horizon_days
      ) e
      where (m.stop_loss is not null and e.low <= m.stop_loss)
        or (m.take_profit_1 is not null and e.high >= m.take_profit_1)
      order by e.trade_date
      limit 1
    ) event on true
  )
  insert into public.v20_signal_outcomes (
    symbol,
    signal_date,
    model_key,
    horizon_days,
    model_version,
    strategy_key,
    market_regime,
    score_decile,
    opportunity_score,
    risk_score,
    confidence,
    up_probability,
    expected_return_net,
    entry_date,
    entry_open,
    horizon_exit_date,
    horizon_close,
    gross_return,
    net_return,
    mfe,
    mae,
    stop_loss,
    take_profit_1,
    plan_exit_date,
    plan_exit_price,
    plan_exit_reason,
    plan_gross_return,
    plan_net_return,
    stop_hit_first,
    target_hit_first,
    buy_commission_rate,
    sell_commission_rate,
    sell_tax_rate,
    slippage_rate_per_side,
    spread_rate_per_side,
    transaction_cost_pct,
    slippage_cost_pct,
    spread_cost_pct,
    total_cost_pct,
    evaluated_as_of,
    evaluated_at,
    updated_at
  )
  select
    e.symbol,
    e.signal_date,
    e.model_key,
    e.horizon_days,
    e.model_version,
    e.strategy_key,
    e.market_regime,
    e.score_decile,
    e.opportunity_score,
    e.risk_score,
    e.confidence,
    e.up_probability,
    e.expected_return_net,
    e.entry_date,
    e.entry_open,
    e.horizon_exit_date,
    e.horizon_close,
    pg_catalog.round((e.horizon_close / e.entry_open - 1) * 100, 4),
    pg_catalog.round((
      (e.horizon_close * (
        1 - p_sell_commission_rate - e.applied_sell_tax_rate
          - p_slippage_rate_per_side - p_spread_rate_per_side
      ))
      / (e.entry_open * (
        1 + p_buy_commission_rate + p_slippage_rate_per_side + p_spread_rate_per_side
      ))
      - 1
    ) * 100, 4),
    pg_catalog.round((e.path_high / e.entry_open - 1) * 100, 4),
    pg_catalog.round((e.path_low / e.entry_open - 1) * 100, 4),
    e.stop_loss,
    e.take_profit_1,
    coalesce(e.event_date, e.horizon_exit_date),
    coalesce(e.event_price, e.horizon_close),
    coalesce(e.event_reason, 'horizon_close'),
    pg_catalog.round((coalesce(e.event_price, e.horizon_close) / e.entry_open - 1) * 100, 4),
    pg_catalog.round((
      (coalesce(e.event_price, e.horizon_close) * (
        1 - p_sell_commission_rate - e.applied_sell_tax_rate
          - p_slippage_rate_per_side - p_spread_rate_per_side
      ))
      / (e.entry_open * (
        1 + p_buy_commission_rate + p_slippage_rate_per_side + p_spread_rate_per_side
      ))
      - 1
    ) * 100, 4),
    e.stop_hit_first,
    e.target_hit_first,
    p_buy_commission_rate,
    p_sell_commission_rate,
    e.applied_sell_tax_rate,
    p_slippage_rate_per_side,
    p_spread_rate_per_side,
    pg_catalog.round(
      (p_buy_commission_rate + p_sell_commission_rate + e.applied_sell_tax_rate) * 100,
      4
    ),
    pg_catalog.round(2 * p_slippage_rate_per_side * 100, 4),
    pg_catalog.round(2 * p_spread_rate_per_side * 100, 4),
    pg_catalog.round((
      p_buy_commission_rate + p_sell_commission_rate + e.applied_sell_tax_rate
        + 2 * p_slippage_rate_per_side + 2 * p_spread_rate_per_side
    ) * 100, 4),
    p_as_of_date,
    pg_catalog.clock_timestamp(),
    pg_catalog.clock_timestamp()
  from evaluated e
  on conflict (symbol, signal_date, model_key, horizon_days, model_version)
  do update set
    strategy_key = excluded.strategy_key,
    market_regime = excluded.market_regime,
    score_decile = excluded.score_decile,
    opportunity_score = excluded.opportunity_score,
    risk_score = excluded.risk_score,
    confidence = excluded.confidence,
    up_probability = excluded.up_probability,
    expected_return_net = excluded.expected_return_net,
    entry_date = excluded.entry_date,
    entry_open = excluded.entry_open,
    horizon_exit_date = excluded.horizon_exit_date,
    horizon_close = excluded.horizon_close,
    gross_return = excluded.gross_return,
    net_return = excluded.net_return,
    mfe = excluded.mfe,
    mae = excluded.mae,
    stop_loss = excluded.stop_loss,
    take_profit_1 = excluded.take_profit_1,
    plan_exit_date = excluded.plan_exit_date,
    plan_exit_price = excluded.plan_exit_price,
    plan_exit_reason = excluded.plan_exit_reason,
    plan_gross_return = excluded.plan_gross_return,
    plan_net_return = excluded.plan_net_return,
    stop_hit_first = excluded.stop_hit_first,
    target_hit_first = excluded.target_hit_first,
    buy_commission_rate = excluded.buy_commission_rate,
    sell_commission_rate = excluded.sell_commission_rate,
    sell_tax_rate = excluded.sell_tax_rate,
    slippage_rate_per_side = excluded.slippage_rate_per_side,
    spread_rate_per_side = excluded.spread_rate_per_side,
    transaction_cost_pct = excluded.transaction_cost_pct,
    slippage_cost_pct = excluded.slippage_cost_pct,
    spread_cost_pct = excluded.spread_cost_pct,
    total_cost_pct = excluded.total_cost_pct,
    evaluated_as_of = excluded.evaluated_as_of,
    evaluated_at = excluded.evaluated_at,
    updated_at = excluded.updated_at
  where excluded.evaluated_as_of >= public.v20_signal_outcomes.evaluated_as_of;

  get diagnostics v_evaluated_rows = row_count;

  select public.twss_v20_refresh_signal_calibration(p_as_of_date, p_model_version)
  into v_calibration;

  return pg_catalog.jsonb_build_object(
    'asOfDate', p_as_of_date,
    'modelVersion', p_model_version,
    'modelKey', p_model_key,
    'limit', p_limit,
    'evaluatedRows', v_evaluated_rows,
    'calibration', v_calibration,
    'generatedAt', pg_catalog.clock_timestamp()
  );
end;
$$;

revoke all on function public.twss_v20_evaluate_signal_outcomes(
  date, text, text, integer, numeric, numeric, numeric, numeric, numeric, numeric
) from public, anon, authenticated;
grant execute on function public.twss_v20_evaluate_signal_outcomes(
  date, text, text, integer, numeric, numeric, numeric, numeric, numeric, numeric
) to service_role;

comment on table public.v20_signal_outcomes is
  'Server-only, immutable-horizon follow-up for published v20 official signals using point-in-time stock_snapshots OHLC.';
comment on function public.twss_v20_evaluate_signal_outcomes(
  date, text, text, integer, numeric, numeric, numeric, numeric, numeric, numeric
) is
  'Service-only SECURITY INVOKER batch: next-session open, Nth-session close, MFE/MAE, stop-first same-bar plan exit, and explicit execution costs, bounded by p_as_of_date and p_limit.';

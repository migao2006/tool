-- v17 phase 4: persistent, no-look-ahead ranking validation and a public
-- explanation of data gaps.  All calculations use data already in Postgres;
-- this migration adds no external API or paid service.

create table if not exists public.opportunity_backtest_outcomes (
  symbol text not null references public.stock_master(symbol) on delete cascade,
  signal_date date not null,
  model_version text not null,
  group_name text not null check (group_name in ('listed', 'otc', 'etf')),
  industry text,
  rank_at_signal integer not null check (rank_at_signal between 1 and 10),
  score_at_signal numeric,
  confidence_at_signal numeric,
  horizon_days integer not null check (horizon_days in (5, 10, 20)),
  signal_finalized_at timestamptz,
  entry_date date not null,
  entry_price numeric not null check (entry_price > 0),
  exit_date date not null,
  exit_price numeric not null check (exit_price > 0),
  return_pct numeric not null,
  benchmark_return_pct numeric,
  excess_return_pct numeric,
  mfe_pct numeric,
  mae_pct numeric,
  market_regime text check (market_regime in ('bull', 'sideways', 'bear', 'unknown')),
  evaluated_at timestamptz not null default now(),
  primary key (symbol, signal_date, model_version, horizon_days)
);

create index if not exists opportunity_backtest_group_horizon_idx
  on public.opportunity_backtest_outcomes
  (group_name, model_version, horizon_days, signal_date desc);

alter table public.opportunity_backtest_outcomes enable row level security;
drop policy if exists opportunity_backtest_outcomes_public_read
  on public.opportunity_backtest_outcomes;
create policy opportunity_backtest_outcomes_public_read
  on public.opportunity_backtest_outcomes
  for select to anon, authenticated using (true);

revoke all on public.opportunity_backtest_outcomes from anon, authenticated;
grant select on public.opportunity_backtest_outcomes to anon, authenticated;
grant all on public.opportunity_backtest_outcomes to service_role;

create or replace function public.twss_evaluate_matured_backtests(
  p_group_name text default null,
  p_model_version text default '16.3'
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  affected integer := 0;
begin
  if p_group_name is not null and p_group_name not in ('listed', 'otc', 'etf') then
    raise exception 'invalid group';
  end if;
  if nullif(pg_catalog.btrim(coalesce(p_model_version, '')), '') is null then
    raise exception 'invalid model version';
  end if;

  with ranked as (
    select
      h.symbol,
      h.score_date as signal_date,
      h.model_version,
      h.group_name,
      m.industry,
      h.score,
      h.confidence,
      c.finalized_at,
      pg_catalog.row_number() over (
        partition by h.group_name, h.score_date, h.model_version
        order by h.score desc nulls last, h.confidence desc, h.symbol
      )::integer as signal_rank
    from public.opportunity_score_history h
    join public.opportunity_ranking_cycles c
      on c.score_date = h.score_date
      and c.model_version = h.model_version
      and c.group_name = h.group_name
      and c.status = 'final'
    join public.stock_master m on m.symbol = h.symbol
    where h.model_version = p_model_version
      and h.official
      and (p_group_name is null or h.group_name = p_group_name)
  ), signals as (
    select r.*, h.horizon_days
    from ranked r
    cross join (values (5), (10), (20)) as h(horizon_days)
    where r.signal_rank <= 10
  ), entries as (
    select s.*, entry.trade_date as entry_date, entry.open as entry_price
    from signals s
    cross join lateral (
      select p.trade_date, p.open
      from public.stock_price_history p
      where p.symbol = s.symbol
        and p.trade_date > s.signal_date
        and p.open is not null
        and p.open > 0
      order by p.trade_date
      limit 1
    ) entry
  ), matured as (
    select e.*, exit_row.trade_date as exit_date, exit_row.close as exit_price
    from entries e
    cross join lateral (
      select p.trade_date, p.close
      from public.stock_price_history p
      where p.symbol = e.symbol
        and p.trade_date >= e.entry_date
        and p.close > 0
      order by p.trade_date
      offset greatest(e.horizon_days - 1, 0)
      limit 1
    ) exit_row
  ), measured as (
    select
      x.*,
      round(((x.exit_price / x.entry_price) - 1) * 100, 6) as return_pct,
      excursion.mfe_pct,
      excursion.mae_pct,
      benchmark.benchmark_return_pct
    from matured x
    cross join lateral (
      select
        round(((max(coalesce(p.high, p.close)) / x.entry_price) - 1) * 100, 6) as mfe_pct,
        round(((min(coalesce(p.low, p.close)) / x.entry_price) - 1) * 100, 6) as mae_pct
      from public.stock_price_history p
      where p.symbol = x.symbol
        and p.trade_date between x.entry_date and x.exit_date
    ) excursion
    left join lateral (
      select round(avg(((peer_exit.close / peer_entry.open) - 1) * 100), 6)
        as benchmark_return_pct
      from public.stock_analysis_cache a
      join public.stock_price_history peer_entry
        on peer_entry.symbol = a.symbol
        and peer_entry.trade_date = x.entry_date
        and peer_entry.open > 0
      join public.stock_price_history peer_exit
        on peer_exit.symbol = a.symbol
        and peer_exit.trade_date = x.exit_date
        and peer_exit.close > 0
      where a.group_name = x.group_name
        and a.status = 'ready'
    ) benchmark on true
  )
  insert into public.opportunity_backtest_outcomes (
    symbol, signal_date, model_version, group_name, industry,
    rank_at_signal, score_at_signal, confidence_at_signal, horizon_days,
    signal_finalized_at, entry_date, entry_price, exit_date, exit_price,
    return_pct, benchmark_return_pct, excess_return_pct, mfe_pct, mae_pct,
    market_regime, evaluated_at
  )
  select
    symbol, signal_date, model_version, group_name, industry,
    signal_rank, score, confidence, horizon_days,
    finalized_at, entry_date, entry_price, exit_date, exit_price,
    return_pct, benchmark_return_pct,
    case when benchmark_return_pct is null then null
      else round(return_pct - benchmark_return_pct, 6) end,
    mfe_pct, mae_pct,
    case when benchmark_return_pct is null then 'unknown'
      when benchmark_return_pct >= 3 then 'bull'
      when benchmark_return_pct <= -3 then 'bear'
      else 'sideways' end,
    clock_timestamp()
  from measured
  on conflict (symbol, signal_date, model_version, horizon_days) do update
  set benchmark_return_pct = excluded.benchmark_return_pct,
      excess_return_pct = excluded.excess_return_pct,
      mfe_pct = excluded.mfe_pct,
      mae_pct = excluded.mae_pct,
      market_regime = excluded.market_regime,
      evaluated_at = clock_timestamp();

  get diagnostics affected = row_count;
  return pg_catalog.jsonb_build_object(
    'status', 'ok',
    'group', p_group_name,
    'modelVersion', p_model_version,
    'rowsAffected', affected,
    'evaluatedAt', clock_timestamp()
  );
end;
$$;

revoke all on function public.twss_evaluate_matured_backtests(text, text)
  from public, anon, authenticated;
grant execute on function public.twss_evaluate_matured_backtests(text, text)
  to service_role;

create or replace function public.twss_public_ranking_backtest(
  p_model_version text default '16.3'
)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
  with groups(group_name) as (
    values ('listed'::text), ('otc'::text), ('etf'::text)
  ), horizons(horizon_days) as (
    values (5), (10), (20)
  ), grid as (
    select g.group_name, h.horizon_days,
      count(distinct o.signal_date)::integer as matured_dates,
      count(o.symbol)::integer as observation_count,
      round(avg(o.return_pct), 2) as average_return,
      round(percentile_cont(0.5) within group (order by o.return_pct)::numeric, 2) as median_return,
      round(avg(o.excess_return_pct), 2) as average_excess_return,
      round((count(*) filter (where o.return_pct > 0))::numeric * 100 /
        nullif(count(o.symbol), 0), 1) as win_rate,
      round((count(*) filter (where o.excess_return_pct > 0))::numeric * 100 /
        nullif(count(o.excess_return_pct), 0), 1) as excess_win_rate,
      round(avg(o.mfe_pct), 2) as average_mfe,
      round(avg(o.mae_pct), 2) as average_mae
    from groups g
    cross join horizons h
    left join public.opportunity_backtest_outcomes o
      on o.group_name = g.group_name
      and o.horizon_days = h.horizon_days
      and o.model_version = p_model_version
    group by g.group_name, h.horizon_days
  ), horizon_payload as (
    select group_name, horizon_days, matured_dates,
      pg_catalog.jsonb_build_object(
        'status', case when matured_dates >= 25 then 'ready' else 'insufficient_history' end,
        'maturedDateCount', matured_dates,
        'minimumSnapshots', 25,
        'count', case when matured_dates >= 25 then observation_count else null end,
        'averageReturn', case when matured_dates >= 25 then average_return else null end,
        'medianReturn', case when matured_dates >= 25 then median_return else null end,
        'averageExcessReturn', case when matured_dates >= 25 then average_excess_return else null end,
        'winRate', case when matured_dates >= 25 then win_rate else null end,
        'excessWinRate', case when matured_dates >= 25 then excess_win_rate else null end,
        'averageMfe', case when matured_dates >= 25 then average_mfe else null end,
        'averageMae', case when matured_dates >= 25 then average_mae else null end
      ) as payload
    from grid
  ), grouped as (
    select group_name,
      pg_catalog.jsonb_object_agg(horizon_days::text, payload order by horizon_days) as payload
    from horizon_payload
    group by group_name
  )
  select pg_catalog.jsonb_build_object(
    'version', '17.0',
    'generatedAt', clock_timestamp(),
    'status', case when exists (
      select 1 from horizon_payload where matured_dates >= 25
    ) then 'ready' else 'insufficient_history' end,
    'snapshotCount', coalesce((select max(matured_dates) from horizon_payload), 0),
    'minimumSnapshots', 25,
    'noLookAhead', true,
    'entryRule', '訊號日後下一交易日官方開盤價',
    'message', case when exists (
      select 1 from horizon_payload where matured_dates >= 25
    ) then '已有市場與期間達到最低成熟樣本門檻。'
      else '各市場與期間至少需要 25 個成熟訊號日；目前仍在後端持續累積。' end,
    'byGroup', coalesce((select pg_catalog.jsonb_object_agg(group_name, payload) from grouped), '{}'::jsonb)
  );
$$;

revoke all on function public.twss_public_ranking_backtest(text) from public;
grant execute on function public.twss_public_ranking_backtest(text)
  to anon, authenticated, service_role;

-- Explain rather than hide non-OK source diagnostics.  This intentionally
-- reports whether a gap is queued for repair, caused by an upstream/API error,
-- objectively unavailable, or not applicable.
create or replace function public.twss_public_missing_data(p_limit integer default 40)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
  with diagnostics as (
    select
      a.symbol,
      a.stock ->> 'name' as name,
      a.group_name,
      a.data_date,
      a.needs_repair,
      a.repair_reasons,
      a.error_kind,
      item.key as dataset_key,
      coalesce(item.value ->> 'status', 'unknown') as source_status,
      item.value as evidence
    from public.stock_analysis_cache a
    cross join lateral pg_catalog.jsonb_each(
      coalesce(a.analysis #> '{sourceDiagnostics}', '{}'::jsonb)
    ) item
    where a.status = 'ready'
      and coalesce(item.value ->> 'status', 'unknown') not in ('ok', 'reused')
  ), classified as (
    select d.*,
      case
        when source_status in ('not-applicable', 'source-not-applicable') then 'not_applicable'
        when needs_repair and dataset_key = any(coalesce(repair_reasons, '{}'::text[])) then 'scheduled_repair'
        when source_status in ('upstream-error', 'error', 'rate-limited') or error_kind is not null then 'upstream_error'
        when source_status = 'stale-source-period' then 'stale_source'
        when source_status = 'empty-no-history' then 'unavailable_from_source'
        else 'partial_source'
      end as classification,
      case
        when source_status in ('not-applicable', 'source-not-applicable') then '此商品不適用該欄位，不列為缺漏'
        when needs_repair and dataset_key = any(coalesce(repair_reasons, '{}'::text[])) then '資料可重試，已排入後端修復隊列'
        when source_status in ('upstream-error', 'error', 'rate-limited') or error_kind is not null then '上游 API 或來源暫時失敗，等待下次重試'
        when source_status = 'stale-source-period' then '公開來源期別落後，等待官方更新'
        when source_status = 'empty-no-history' then 'API 已回應，但公開來源沒有該檔歷史資料'
        else '來源只提供部分欄位，系統不以 0 分代替'
      end as reason
    from diagnostics d
  ), summary as (
    select dataset_key, classification, count(*)::integer as count
    from classified
    group by dataset_key, classification
  ), examples as (
    select * from classified
    order by (needs_repair and dataset_key = any(coalesce(repair_reasons, '{}'::text[]))) desc,
      data_date desc nulls last, symbol, dataset_key
    limit greatest(1, least(coalesce(p_limit, 40), 100))
  )
  select pg_catalog.jsonb_build_object(
    'generatedAt', clock_timestamp(),
    'summary', coalesce((select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
      'dataset', dataset_key, 'classification', classification, 'count', count
    ) order by dataset_key, classification) from summary), '[]'::jsonb),
    'examples', coalesce((select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
      'symbol', symbol, 'name', name, 'group', group_name, 'dataDate', data_date,
      'dataset', dataset_key, 'sourceStatus', source_status,
      'classification', classification, 'retryable',
        (needs_repair and dataset_key = any(coalesce(repair_reasons, '{}'::text[]))),
      'repairReasons', repair_reasons, 'reason', reason, 'evidence', evidence
    )) from examples), '[]'::jsonb)
  );
$$;

revoke all on function public.twss_public_missing_data(integer) from public;
grant execute on function public.twss_public_missing_data(integer)
  to anon, authenticated, service_role;

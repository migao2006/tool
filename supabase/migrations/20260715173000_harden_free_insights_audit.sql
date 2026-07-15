-- v17 final audit hardening.  This patch is intentionally additive so an
-- existing project that already ran the earlier v17 migrations can apply it
-- safely.  It changes only observation/reporting logic, never score weights.

-- A cycle is final only when the immutable score history contains every row
-- the completed deep job said to expect.  Never lower the expected population
-- merely to make an incomplete day look complete.
create or replace function public.twss_finalize_ranking_cycle(
  p_group_name text,
  p_score_date date,
  p_model_version text,
  p_expected_count integer default 0
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_scored integer := 0;
  v_official integer := 0;
  v_existing_expected integer := 0;
  v_expected integer := 0;
begin
  if p_group_name not in ('listed', 'otc', 'etf')
    or p_score_date is null
    or nullif(pg_catalog.btrim(coalesce(p_model_version, '')), '') is null
  then
    raise exception 'ranking_cycle_invalid';
  end if;

  select coalesce(c.expected_count, 0)
  into v_existing_expected
  from public.opportunity_ranking_cycles c
  where c.group_name = p_group_name
    and c.score_date = p_score_date
    and c.model_version = p_model_version;

  v_expected := greatest(coalesce(p_expected_count, 0), coalesce(v_existing_expected, 0));
  if v_expected <= 0 then
    raise exception 'ranking_cycle_expected_count_required';
  end if;

  select count(*), count(*) filter (where h.official)
  into v_scored, v_official
  from public.opportunity_score_history h
  where h.group_name = p_group_name
    and h.score_date = p_score_date
    and h.model_version = p_model_version;

  if v_scored < v_expected then
    raise exception 'ranking_cycle_incomplete';
  end if;

  insert into public.opportunity_ranking_cycles (
    score_date, model_version, group_name, status, expected_count,
    scored_count, official_count, finalized_at, updated_at
  ) values (
    p_score_date, p_model_version, p_group_name, 'final', v_expected,
    v_scored, v_official, clock_timestamp(), clock_timestamp()
  )
  on conflict (score_date, model_version, group_name) do update
  set status = 'final',
      expected_count = greatest(
        public.opportunity_ranking_cycles.expected_count,
        excluded.expected_count
      ),
      scored_count = excluded.scored_count,
      official_count = excluded.official_count,
      finalized_at = coalesce(
        public.opportunity_ranking_cycles.finalized_at,
        excluded.finalized_at
      ),
      updated_at = clock_timestamp();

  return pg_catalog.jsonb_build_object(
    'group', p_group_name,
    'scoreDate', p_score_date,
    'modelVersion', p_model_version,
    'expected', v_expected,
    'scored', v_scored,
    'official', v_official,
    'status', 'final'
  );
end;
$$;

revoke all on function public.twss_finalize_ranking_cycle(text, date, text, integer)
  from public, anon, authenticated;
grant execute on function public.twss_finalize_ranking_cycle(text, date, text, integer)
  to service_role;

-- Recount existing rows exactly.  Any legacy row that was finalized below its
-- expected population goes back to building instead of remaining public.
with actual as (
  select
    c.score_date,
    c.model_version,
    c.group_name,
    count(h.symbol)::integer as scored_count,
    count(h.symbol) filter (where h.official)::integer as official_count
  from public.opportunity_ranking_cycles c
  left join public.opportunity_score_history h
    on h.score_date = c.score_date
    and h.model_version = c.model_version
    and h.group_name = c.group_name
  group by c.score_date, c.model_version, c.group_name
)
update public.opportunity_ranking_cycles c
set scored_count = a.scored_count,
    official_count = a.official_count,
    status = case
      when a.scored_count >= c.expected_count and c.expected_count > 0 then c.status
      else 'building'
    end,
    finalized_at = case
      when a.scored_count >= c.expected_count and c.expected_count > 0 then c.finalized_at
      else null
    end,
    updated_at = clock_timestamp()
from actual a
where a.score_date = c.score_date
  and a.model_version = c.model_version
  and a.group_name = c.group_name;

-- Once final, the score cross-section is point-in-time evidence.  Later same-
-- day refreshes may update the live analysis cache but must silently preserve
-- the finalized history row so scheduled refreshes do not fail or rewrite the
-- backtest signal after the fact.
create or replace function public.twss_preserve_final_score_history()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if tg_op = 'UPDATE' then
    if exists (
      select 1
      from public.opportunity_ranking_cycles c
      where c.score_date = old.score_date
        and c.model_version = old.model_version
        and c.group_name = old.group_name
        and c.status = 'final'
    ) then
      return old;
    end if;
  end if;

  if exists (
    select 1
    from public.opportunity_ranking_cycles c
    where c.score_date = new.score_date
      and c.model_version = new.model_version
      and c.group_name = new.group_name
      and c.status = 'final'
  ) then
    if tg_op = 'UPDATE' then return old; end if;
    return null;
  end if;

  return new;
end;
$$;

revoke all on function public.twss_preserve_final_score_history()
  from public, anon, authenticated;
drop trigger if exists preserve_final_score_history on public.opportunity_score_history;
create trigger preserve_final_score_history
before insert or update on public.opportunity_score_history
for each row execute function public.twss_preserve_final_score_history();

-- Peer percentiles must compare the target only with rows from the exact same
-- analysis date and version.  PE values <= 0 are economically inapplicable,
-- and ETF discount/premium quality is distance from zero, not signed value.
drop function if exists public.twss_get_stock_context(text);
drop function if exists public.twss_peer_metric(text, text, text, text, numeric, boolean);
drop function if exists public.twss_peer_metric(text, text, text, date, text, text, numeric, boolean);

create function public.twss_peer_metric(
  p_group_name text,
  p_industry text,
  p_scope text,
  p_data_date date,
  p_analysis_version text,
  p_metric_key text,
  p_target numeric,
  p_higher_is_better boolean
)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
  with peer_values as (
    select case p_metric_key
      when 'score' then a.score
      when 'revenue_avg3' then nullif(a.analysis #>> '{revenue,avg3Yoy}', '')::numeric
      when 'revenue_acceleration' then nullif(a.analysis #>> '{revenue,acceleration3}', '')::numeric
      when 'operating_margin' then nullif(a.analysis #>> '{financial,operatingMargin}', '')::numeric
      when 'cash_conversion' then nullif(a.analysis #>> '{financial,cashConversion}', '')::numeric
      when 'institutional_intensity' then nullif(a.analysis #>> '{institutional,intensity5}', '')::numeric
      when 'relative_strength20' then nullif(a.analysis #>> '{price,relative20}', '')::numeric
      when 'volume_ratio' then nullif(a.analysis #>> '{price,volumeRatio}', '')::numeric
      when 'atr_pct' then nullif(a.analysis #>> '{price,atrPct}', '')::numeric
      when 'pe' then case
        when nullif(a.stock ->> 'pe', '')::numeric > 0
          then nullif(a.stock ->> 'pe', '')::numeric
        else null
      end
      when 'premium_discount' then pg_catalog.abs(
        nullif(a.analysis #>> '{etf,premiumDiscount}', '')::numeric
      )
      else null
    end as metric_value
    from public.stock_analysis_cache a
    where a.group_name = p_group_name
      and a.status = 'ready'
      and a.data_date = p_data_date
      and a.analysis_version = p_analysis_version
      and (p_scope = 'group_fallback' or a.stock ->> 'industry' = p_industry)
  ), summary as (
    select
      count(*) filter (where metric_value is not null) as available_count,
      percentile_cont(0.5) within group (order by metric_value)
        filter (where metric_value is not null) as median_value,
      count(*) filter (
        where metric_value is not null and p_target is not null
          and case
            when p_higher_is_better then metric_value <= p_target
            else metric_value >= p_target
          end
      ) as favorable_count
    from peer_values
  )
  select pg_catalog.jsonb_build_object(
    'key', p_metric_key,
    'value', p_target,
    'median', median_value,
    'percentile', case
      when p_target is null or available_count = 0 then null
      else round((favorable_count::numeric * 100) / available_count, 1)
    end,
    'availableCount', available_count,
    'higherIsBetter', p_higher_is_better
  )
  from summary;
$$;

revoke all on function public.twss_peer_metric(text, text, text, date, text, text, numeric, boolean)
  from public;
grant execute on function public.twss_peer_metric(text, text, text, date, text, text, numeric, boolean)
  to anon, authenticated, service_role;

create function public.twss_get_stock_context(p_symbol text)
returns jsonb
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
  target public.stock_analysis_cache%rowtype;
  v_industry text;
  v_scope text;
  v_peer_count integer;
  v_metrics jsonb;
  v_series jsonb;
  v_final_dates integer;
begin
  if p_symbol !~ '^[0-9]{4,6}[A-Za-z]?$' then
    raise exception 'invalid_symbol';
  end if;

  select * into target
  from public.stock_analysis_cache
  where symbol = p_symbol and status = 'ready'
  limit 1;

  if not found then
    return pg_catalog.jsonb_build_object('available', false, 'symbol', p_symbol);
  end if;

  v_industry := coalesce(target.stock ->> 'industry', '未分類');
  select count(*) into v_peer_count
  from public.stock_analysis_cache a
  where a.group_name = target.group_name
    and a.status = 'ready'
    and a.data_date = target.data_date
    and a.analysis_version = target.analysis_version
    and a.stock ->> 'industry' = v_industry;

  v_scope := case when v_peer_count >= 5 then 'industry' else 'group_fallback' end;
  if v_scope = 'group_fallback' then
    select count(*) into v_peer_count
    from public.stock_analysis_cache a
    where a.group_name = target.group_name
      and a.status = 'ready'
      and a.data_date = target.data_date
      and a.analysis_version = target.analysis_version;
  end if;

  if target.group_name = 'etf' then
    v_metrics := pg_catalog.jsonb_build_array(
      public.twss_peer_metric(target.group_name, v_industry, v_scope, target.data_date, target.analysis_version,
        'score', target.score, true),
      public.twss_peer_metric(target.group_name, v_industry, v_scope, target.data_date, target.analysis_version,
        'relative_strength20', nullif(target.analysis #>> '{price,relative20}', '')::numeric, true),
      public.twss_peer_metric(target.group_name, v_industry, v_scope, target.data_date, target.analysis_version,
        'volume_ratio', nullif(target.analysis #>> '{price,volumeRatio}', '')::numeric, true),
      public.twss_peer_metric(target.group_name, v_industry, v_scope, target.data_date, target.analysis_version,
        'premium_discount', pg_catalog.abs(nullif(target.analysis #>> '{etf,premiumDiscount}', '')::numeric), false),
      public.twss_peer_metric(target.group_name, v_industry, v_scope, target.data_date, target.analysis_version,
        'atr_pct', nullif(target.analysis #>> '{price,atrPct}', '')::numeric, false)
    );
  else
    v_metrics := pg_catalog.jsonb_build_array(
      public.twss_peer_metric(target.group_name, v_industry, v_scope, target.data_date, target.analysis_version,
        'score', target.score, true),
      public.twss_peer_metric(target.group_name, v_industry, v_scope, target.data_date, target.analysis_version,
        'revenue_avg3', nullif(target.analysis #>> '{revenue,avg3Yoy}', '')::numeric, true),
      public.twss_peer_metric(target.group_name, v_industry, v_scope, target.data_date, target.analysis_version,
        'revenue_acceleration', nullif(target.analysis #>> '{revenue,acceleration3}', '')::numeric, true),
      public.twss_peer_metric(target.group_name, v_industry, v_scope, target.data_date, target.analysis_version,
        'operating_margin', nullif(target.analysis #>> '{financial,operatingMargin}', '')::numeric, true),
      public.twss_peer_metric(target.group_name, v_industry, v_scope, target.data_date, target.analysis_version,
        'cash_conversion', nullif(target.analysis #>> '{financial,cashConversion}', '')::numeric, true),
      public.twss_peer_metric(target.group_name, v_industry, v_scope, target.data_date, target.analysis_version,
        'institutional_intensity', nullif(target.analysis #>> '{institutional,intensity5}', '')::numeric, true),
      public.twss_peer_metric(target.group_name, v_industry, v_scope, target.data_date, target.analysis_version,
        'relative_strength20', nullif(target.analysis #>> '{price,relative20}', '')::numeric, true),
      public.twss_peer_metric(target.group_name, v_industry, v_scope, target.data_date, target.analysis_version,
        'pe', case when nullif(target.stock ->> 'pe', '')::numeric > 0
          then nullif(target.stock ->> 'pe', '')::numeric else null end, false)
    );
  end if;

  select count(*) into v_final_dates
  from public.opportunity_ranking_cycles
  where group_name = target.group_name
    and model_version = '16.3'
    and status = 'final';

  with ranked as (
    select h.symbol, h.score_date, h.score, h.confidence,
      rank() over (
        partition by h.score_date
        order by h.score desc nulls last, h.confidence desc
      ) as rank_value
    from public.opportunity_score_history h
    join public.opportunity_ranking_cycles c
      on c.group_name = h.group_name
      and c.score_date = h.score_date
      and c.model_version = h.model_version
      and c.status = 'final'
    where h.group_name = target.group_name
      and h.model_version = '16.3'
      and h.official
  )
  select coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
    'date', score_date, 'score', score, 'confidence', confidence, 'rank', rank_value
  ) order by score_date), '[]'::jsonb)
  into v_series
  from (
    select * from ranked
    where symbol = p_symbol
    order by score_date desc
    limit 20
  ) recent;

  return pg_catalog.jsonb_build_object(
    'available', true,
    'symbol', p_symbol,
    'group', target.group_name,
    'industry', v_industry,
    'peer', pg_catalog.jsonb_build_object(
      'scope', v_scope,
      'peerCount', v_peer_count,
      'dataDate', target.data_date,
      'analysisVersion', target.analysis_version,
      'metrics', v_metrics
    ),
    'trend', pg_catalog.jsonb_build_object(
      'status', case when v_final_dates >= 2 then 'ready' else 'accumulating' end,
      'finalDateCount', v_final_dates,
      'minimumFinalDates', 2,
      'series', v_series
    )
  );
end;
$$;

revoke all on function public.twss_get_stock_context(text) from public;
grant execute on function public.twss_get_stock_context(text)
  to anon, authenticated, service_role;

-- Data-health history is complete only to the weakest independent group.
-- Official counts are tied to the exact score date and model version.  Public
-- output exposes stable diagnostic codes, never internal upstream text.
create or replace function public.twss_public_data_health()
returns jsonb
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
  universe record;
  v_groups jsonb;
  v_sources jsonb;
  v_repairs integer := 0;
  v_errors integer := 0;
  v_final_dates integer := 0;
  v_final_by_group jsonb := '{}'::jsonb;
  v_latest_common_final date;
  v_overall text;
begin
  select * into universe
  from public.stock_sync_state
  where job_key = 'universe'
  limit 1;

  select coalesce(pg_catalog.jsonb_object_agg(group_name, payload), '{}'::jsonb)
  into v_groups
  from (
    select s.group_name, pg_catalog.jsonb_build_object(
      'status', s.status,
      'dataDate', s.cycle_date,
      'modelVersion', '16.3',
      'eligible', s.total_items,
      'verified', s.processed_count,
      'official', (
        select count(*)
        from public.opportunity_score_history h
        where h.group_name = s.group_name
          and h.score_date = s.cycle_date
          and h.model_version = '16.3'
          and h.official
      ),
      'ratio', case when s.total_items > 0
        then round(s.processed_count::numeric * 100 / s.total_items, 1)
        else 0 end,
      'lastSuccessAt', s.last_success_at,
      'nextRunAt', s.next_run_at,
      'lastErrorCode', case
        when s.last_error is null then null
        when lower(s.last_error) ~ '(429|rate.?limit|quota)' then 'rate_limited'
        when lower(s.last_error) ~ '(timeout|abort)' then 'upstream_timeout'
        else 'sync_error'
      end
    ) payload
    from public.stock_sync_state s
    where s.job_key in ('deep_listed', 'deep_otc', 'deep_etf')
  ) grouped;

  select count(*) filter (where needs_repair), count(*) filter (where status = 'error')
  into v_repairs, v_errors
  from public.stock_analysis_cache;

  with market_groups(group_name) as (
    values ('listed'::text), ('otc'::text), ('etf'::text)
  ), counts as (
    select g.group_name,
      count(distinct c.score_date)::integer as final_count,
      max(c.score_date) as latest_final_date
    from market_groups g
    left join public.opportunity_ranking_cycles c
      on c.group_name = g.group_name
      and c.model_version = '16.3'
      and c.status = 'final'
    group by g.group_name
  ), common_dates as (
    select c.score_date
    from public.opportunity_ranking_cycles c
    where c.model_version = '16.3'
      and c.status = 'final'
      and c.group_name in ('listed', 'otc', 'etf')
    group by c.score_date
    having count(distinct c.group_name) = 3
  )
  select
    coalesce(pg_catalog.jsonb_object_agg(group_name, pg_catalog.jsonb_build_object(
      'finalDateCount', final_count,
      'latestFinalDate', latest_final_date
    )), '{}'::jsonb),
    coalesce(min(final_count), 0),
    (select max(score_date) from common_dates)
  into v_final_by_group, v_final_dates, v_latest_common_final
  from counts;

  v_sources := pg_catalog.jsonb_build_object(
    'price', pg_catalog.jsonb_build_object(
      'label', '每日行情',
      'status', case when universe.details #>> '{sources,stocks,dates,price,latest}' is null
        then 'missing' else 'healthy' end,
      'latest', universe.details #>> '{sources,stocks,dates,price,latest}',
      'covered', coalesce((universe.details #>> '{sources,stocks,count}')::integer, 0),
      'reasonCode', case when universe.details #>> '{sources,stocks,dates,price,latest}' is null
        then 'source_missing' else null end
    ),
    'revenue', pg_catalog.jsonb_build_object(
      'label', '月營收',
      'status', case
        when coalesce((universe.details #>> '{sources,revenue,rows}')::integer, 0) = 0 then 'missing'
        when coalesce((universe.details #>> '{sources,revenue,missingAmount}')::integer, 0) > 0 then 'partial'
        else 'healthy' end,
      'latest', universe.details #>> '{sources,revenue,period}',
      'covered', coalesce((universe.details #>> '{sources,revenue,matched}')::integer, 0),
      'missing', coalesce((universe.details #>> '{sources,revenue,missingAmount}')::integer, 0),
      'reasonCode', case
        when coalesce((universe.details #>> '{sources,revenue,rows}')::integer, 0) = 0 then 'source_empty'
        when coalesce((universe.details #>> '{sources,revenue,missingAmount}')::integer, 0) > 0 then 'partial_coverage'
        else null end
    ),
    'financial', pg_catalog.jsonb_build_object(
      'label', '季度財報',
      'status', case when coalesce((universe.details #>> '{sources,financial,rows}')::integer, 0) = 0
        then 'missing' else 'healthy' end,
      'latest', universe.details #>> '{sources,financial,period}',
      'covered', coalesce((universe.details #>> '{sources,financial,matched}')::integer, 0),
      'reasonCode', case when coalesce((universe.details #>> '{sources,financial,rows}')::integer, 0) = 0
        then 'source_empty' else null end
    ),
    'institutional', pg_catalog.jsonb_build_object(
      'label', '法人籌碼',
      'status', case when universe.details #>> '{sources,stocks,dates,institutional,latest}' is null
        then 'missing' else 'healthy' end,
      'latest', universe.details #>> '{sources,stocks,dates,institutional,latest}',
      'covered', coalesce((universe.details #>> '{sources,stocks,count}')::integer, 0),
      'reasonCode', case when universe.details #>> '{sources,stocks,dates,institutional,latest}' is null
        then 'source_missing' else null end
    ),
    'margin', pg_catalog.jsonb_build_object(
      'label', '融資融券',
      'status', case when universe.details #>> '{sources,stocks,dates,margin,latest}' is null
        then 'missing' else 'healthy' end,
      'latest', universe.details #>> '{sources,stocks,dates,margin,latest}',
      'covered', coalesce((universe.details #>> '{sources,stocks,count}')::integer, 0),
      'reasonCode', case when universe.details #>> '{sources,stocks,dates,margin,latest}' is null
        then 'source_missing' else null end
    ),
    'holdings', pg_catalog.jsonb_build_object(
      'label', '集保持股',
      'status', case
        when universe.details #>> '{sources,holdings,error}' is not null then 'error'
        when universe.details #>> '{sources,holdings,date}' is null then 'missing'
        else 'healthy' end,
      'latest', universe.details #>> '{sources,holdings,date}',
      'covered', coalesce((universe.details #>> '{sources,holdings,rows}')::integer, 0),
      'reasonCode', case
        when universe.details #>> '{sources,holdings,error}' is not null then 'upstream_error'
        when universe.details #>> '{sources,holdings,date}' is null then 'source_empty'
        else null end
    ),
    'benchmark', pg_catalog.jsonb_build_object(
      'label', '市場基準',
      'status', case
        when coalesce((universe.details #>> '{sources,benchmarks,coverage,listed}')::boolean, false)
          and coalesce((universe.details #>> '{sources,benchmarks,coverage,otc}')::boolean, false)
          then 'healthy' else 'partial' end,
      'latest', universe.cycle_date,
      'covered', (
        case when coalesce((universe.details #>> '{sources,benchmarks,coverage,listed}')::boolean, false) then 1 else 0 end
        + case when coalesce((universe.details #>> '{sources,benchmarks,coverage,otc}')::boolean, false) then 1 else 0 end
      ),
      'total', 2,
      'reasonCode', case
        when coalesce((universe.details #>> '{sources,benchmarks,coverage,listed}')::boolean, false)
          and coalesce((universe.details #>> '{sources,benchmarks,coverage,otc}')::boolean, false)
          then null else 'benchmark_incomplete' end
    )
  );

  v_overall := case
    when universe.status = 'error' or v_errors > 0 then 'error'
    when v_repairs > 0 or universe.status in ('partial', 'pending') then 'warning'
    else 'healthy'
  end;

  return pg_catalog.jsonb_build_object(
    'version', '17.1',
    'generatedAt', clock_timestamp(),
    'dataDate', universe.cycle_date,
    'overallStatus', v_overall,
    'sources', v_sources,
    'groups', v_groups,
    'repairQueue', pg_catalog.jsonb_build_object('pending', v_repairs, 'errors', v_errors),
    'scoreHistory', pg_catalog.jsonb_build_object(
      'status', case when v_final_dates >= 2 then 'ready' else 'accumulating' end,
      'finalDateCount', v_final_dates,
      'minimumFinalDates', 2,
      'latestCommonFinalDate', v_latest_common_final,
      'perGroup', v_final_by_group
    ),
    'costPolicy', '只使用既有公開資料與資料庫計算，不呼叫付費 AI'
  );
end;
$$;

revoke all on function public.twss_public_data_health() from public;
grant execute on function public.twss_public_data_health()
  to anon, authenticated, service_role;

-- Enter only after the cycle was actually finalized in Taipei, and choose the
-- next stored trading-day open after the later of signal date/finalization
-- date.  Benchmark membership comes from that historical score cross-section,
-- never today's analysis cache.  Market regime remains unknown until a
-- separate pre-signal benchmark series is available.
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
    raise exception 'invalid_group';
  end if;
  if nullif(pg_catalog.btrim(coalesce(p_model_version, '')), '') is null then
    raise exception 'invalid_model_version';
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
      and c.finalized_at is not null
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
        and p.trade_date > greatest(
          s.signal_date,
          (s.finalized_at at time zone 'Asia/Taipei')::date
        )
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
      from public.opportunity_score_history membership
      join public.stock_price_history peer_entry
        on peer_entry.symbol = membership.symbol
        and peer_entry.trade_date = x.entry_date
        and peer_entry.open > 0
      join public.stock_price_history peer_exit
        on peer_exit.symbol = membership.symbol
        and peer_exit.trade_date = x.exit_date
        and peer_exit.close > 0
      where membership.group_name = x.group_name
        and membership.score_date = x.signal_date
        and membership.model_version = x.model_version
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
    mfe_pct, mae_pct, 'unknown', clock_timestamp()
  from measured
  on conflict (symbol, signal_date, model_version, horizon_days) do update
  set signal_finalized_at = excluded.signal_finalized_at,
      entry_date = excluded.entry_date,
      entry_price = excluded.entry_price,
      exit_date = excluded.exit_date,
      exit_price = excluded.exit_price,
      return_pct = excluded.return_pct,
      benchmark_return_pct = excluded.benchmark_return_pct,
      excess_return_pct = excluded.excess_return_pct,
      mfe_pct = excluded.mfe_pct,
      mae_pct = excluded.mae_pct,
      market_regime = 'unknown',
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

-- Quarantine legacy outcomes produced by the superseded rules.  Invalid entry
-- rows are removed; future-period benchmark fields are hidden until the next
-- stored-data evaluation recomputes them with point-in-time membership.
delete from public.opportunity_backtest_outcomes o
where not exists (
  select 1
  from public.opportunity_ranking_cycles c
  where c.score_date = o.signal_date
    and c.model_version = o.model_version
    and c.group_name = o.group_name
    and c.status = 'final'
    and c.finalized_at is not null
    and o.entry_date > greatest(
      o.signal_date,
      (c.finalized_at at time zone 'Asia/Taipei')::date
    )
);

update public.opportunity_backtest_outcomes
set benchmark_return_pct = null,
    excess_return_pct = null,
    market_regime = 'unknown',
    evaluated_at = clock_timestamp();

create or replace function public.twss_public_missing_data(p_limit integer default 40)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
  with raw_diagnostics as (
    select
      a.symbol,
      a.stock ->> 'name' as name,
      a.group_name,
      a.data_date,
      a.error_kind,
      a.needs_repair,
      a.repair_reasons,
      case
        when item.key = 'revenue' then 'monthly_revenue'
        when item.key = 'price' then 'price_history'
        when item.key = 'profile' and a.group_name = 'etf' then 'etf_profile'
        else item.key
      end as dataset_key,
      coalesce(item.value ->> 'status', 'unknown') as source_status,
      item.value as source_evidence
    from public.stock_analysis_cache a
    cross join lateral pg_catalog.jsonb_each(
      coalesce(a.analysis #> '{sourceDiagnostics}', '{}'::jsonb)
    ) item
    where a.status = 'ready'
      and coalesce(item.value ->> 'status', 'unknown') not in ('ok', 'reused')

    union all

    select a.symbol, a.stock ->> 'name', a.group_name, a.data_date,
      a.error_kind, a.needs_repair, a.repair_reasons,
      'monthly_revenue', 'field-missing',
      pg_catalog.jsonb_build_object(
        'status', 'field-missing',
        'expectedPeriod', a.analysis #>> '{sourceDiagnostics,revenue,expectedPeriod}',
        'actualPeriod', a.analysis #>> '{sourceDiagnostics,revenue,actualPeriod}'
      )
    from public.stock_analysis_cache a
    where a.status = 'ready'
      and a.group_name <> 'etf'
      and coalesce(a.analysis #>> '{revenue,revenue}', a.stock ->> 'revenue') is null
      and coalesce(a.analysis #>> '{sourceDiagnostics,revenue,status}', 'unknown') in ('ok', 'reused')

    union all

    select a.symbol, a.stock ->> 'name', a.group_name, a.data_date,
      a.error_kind, a.needs_repair, a.repair_reasons,
      'holdings', 'field-missing',
      pg_catalog.jsonb_build_object('status', 'field-missing')
    from public.stock_analysis_cache a
    where a.status = 'ready'
      and a.group_name <> 'etf'
      and a.analysis #>> '{holdings}' is null
      and coalesce(a.analysis #>> '{sourceDiagnostics,holdings,status}', 'unknown') in ('ok', 'reused')

    union all

    select a.symbol, a.stock ->> 'name', a.group_name, a.data_date,
      a.error_kind, false, '{}'::text[],
      'etf_profile', 'field-missing',
      pg_catalog.jsonb_build_object('status', 'field-missing')
    from public.stock_analysis_cache a
    where a.status = 'ready'
      and a.group_name = 'etf'
      and a.analysis #>> '{etf}' is null
      and coalesce(a.analysis #>> '{sourceDiagnostics,profile,status}', 'unknown') in ('ok', 'reused')

    union all

    select a.symbol, a.stock ->> 'name', a.group_name, a.data_date,
      a.error_kind, false, '{}'::text[],
      'etf_premium_discount', 'field-missing',
      pg_catalog.jsonb_build_object('status', 'field-missing')
    from public.stock_analysis_cache a
    where a.status = 'ready'
      and a.group_name = 'etf'
      and a.analysis #>> '{etf,premiumDiscount}' is null

    union all

    select a.symbol, a.stock ->> 'name', a.group_name, a.data_date,
      a.error_kind, false, '{}'::text[],
      gap.dataset_key, 'official-not-provided',
      pg_catalog.jsonb_build_object('status', 'official-not-provided')
    from public.stock_analysis_cache a
    cross join lateral (
      values
        ('etf_tracking_error'::text, a.analysis #>> '{etf,trackingError}'),
        ('etf_fees'::text, a.analysis #>> '{etf,fees}'),
        ('etf_top10_concentration'::text, a.analysis #>> '{etf,top10Concentration}')
    ) gap(dataset_key, field_value)
    where a.status = 'ready'
      and a.group_name = 'etf'
      and gap.field_value is null

    union all

    select a.symbol, a.stock ->> 'name', a.group_name, a.data_date,
      a.error_kind, a.needs_repair, a.repair_reasons,
      'quarterly_revenue', case
        when a.analysis #>> '{financial,revenueStatus}' = 'source-not-comparable'
          then 'source-not-applicable'
        else 'field-missing'
      end,
      pg_catalog.jsonb_build_object(
        'status', case
          when a.analysis #>> '{financial,revenueStatus}' = 'source-not-comparable'
            then 'source-not-applicable'
          else 'field-missing'
        end,
        'actualPeriod', a.analysis #>> '{financial,period}'
      )
    from public.stock_analysis_cache a
    where a.status = 'ready'
      and a.group_name <> 'etf'
      and coalesce(a.analysis #>> '{financial,revenue}', a.stock ->> 'quarterRevenue') is null

    union all

    select a.symbol, a.stock ->> 'name', a.group_name, a.data_date,
      a.error_kind, a.needs_repair, a.repair_reasons,
      'cash_conversion', case
        when a.analysis #>> '{financial,cashConversionBasis}' = 'TTM-nonpositive-net-income'
          and coalesce((a.analysis #>> '{financial,sourceCoverage,cashflowRows}')::integer, 0) > 0
          then 'source-not-applicable'
        when coalesce((a.analysis #>> '{financial,sourceCoverage,cashflowRows}')::integer, 0) = 0
          then 'empty-no-history'
        else 'field-missing'
      end,
      pg_catalog.jsonb_build_object(
        'status', case
          when a.analysis #>> '{financial,cashConversionBasis}' = 'TTM-nonpositive-net-income'
            and coalesce((a.analysis #>> '{financial,sourceCoverage,cashflowRows}')::integer, 0) > 0
            then 'source-not-applicable'
          when coalesce((a.analysis #>> '{financial,sourceCoverage,cashflowRows}')::integer, 0) = 0
            then 'empty-no-history'
          else 'field-missing'
        end,
        'actualPeriod', a.analysis #>> '{financial,period}'
      )
    from public.stock_analysis_cache a
    where a.status = 'ready'
      and a.group_name <> 'etf'
      and a.analysis #>> '{financial,cashConversion}' is null

    union all

    select a.symbol, a.stock ->> 'name', a.group_name, a.data_date,
      a.error_kind, false, '{}'::text[], depth.dataset_key, 'insufficient-history',
      pg_catalog.jsonb_build_object('status', 'insufficient-history', 'rows', depth.actual_rows)
    from public.stock_analysis_cache a
    cross join lateral (
      values
        ('price_history'::text, coalesce((a.analysis #>> '{price,rows}')::integer, 0), 120),
        ('monthly_revenue'::text, case when a.group_name = 'etf' then 24
          else coalesce((a.analysis #>> '{revenue,months}')::integer, 0) end, 24),
        ('quarterly_financials'::text, case when a.group_name = 'etf' then 8
          else coalesce((a.analysis #>> '{financial,quarters}')::integer, 0) end, 8),
        ('institutional'::text, case when a.group_name = 'etf' then 20
          else coalesce((a.analysis #>> '{institutional,days}')::integer, 0) end, 20),
        ('margin'::text, case when a.group_name = 'etf' then 20
          else coalesce((a.analysis #>> '{margin,days}')::integer, 0) end, 20)
    ) depth(dataset_key, actual_rows, required_rows)
    where a.status = 'ready'
      and depth.actual_rows < depth.required_rows
      and case depth.dataset_key
        when 'price_history' then coalesce(a.analysis #>> '{sourceDiagnostics,price,status}', 'unknown') in ('ok', 'reused')
        when 'monthly_revenue' then coalesce(a.analysis #>> '{sourceDiagnostics,revenue,status}', 'unknown') in ('ok', 'reused')
        when 'quarterly_financials' then coalesce(a.analysis #>> '{sourceDiagnostics,income,status}', 'unknown') in ('ok', 'reused')
        when 'institutional' then coalesce(a.analysis #>> '{sourceDiagnostics,institutional,status}', 'unknown') in ('ok', 'reused')
        when 'margin' then coalesce(a.analysis #>> '{sourceDiagnostics,margin,status}', 'unknown') in ('ok', 'reused')
        else false
      end

    union all

    select a.symbol, a.stock ->> 'name', a.group_name, a.data_date,
      a.error_kind, true, array['deep_refresh']::text[],
      'deep_refresh', 'upstream-error',
      pg_catalog.jsonb_build_object('status', 'upstream-error')
    from public.stock_analysis_cache a
    where a.status = 'ready'
      and a.error_kind is not null

    union all

    select a.symbol, a.stock ->> 'name', a.group_name, a.data_date,
      a.error_kind, true, array['deep_analysis']::text[],
      'deep_analysis', 'upstream-error',
      pg_catalog.jsonb_build_object('status', 'upstream-error')
    from public.stock_analysis_cache a
    where a.status = 'error'
  ), base as (
    select
      r.symbol,
      r.name,
      r.group_name,
      r.data_date,
      r.error_kind,
      r.dataset_key,
      r.source_status,
      (
        r.source_status not in ('not-applicable', 'source-not-applicable')
        and r.needs_repair and (
          r.dataset_key = any(coalesce(r.repair_reasons, '{}'::text[]))
          or 'v16.3-source-coverage-audit' = any(coalesce(r.repair_reasons, '{}'::text[]))
          or (
            'financial-source-coverage' = any(coalesce(r.repair_reasons, '{}'::text[]))
            and r.dataset_key in ('income', 'balance', 'cashflow', 'quarterly_revenue', 'cash_conversion')
          )
          or (
            'revenue' = any(coalesce(r.repair_reasons, '{}'::text[]))
            and r.dataset_key = 'monthly_revenue'
          )
        )
      ) as retryable,
      pg_catalog.jsonb_strip_nulls(pg_catalog.jsonb_build_object(
        'status', r.source_status,
        'statusCode', case when coalesce(r.source_evidence ->> 'statusCode', '') ~ '^[1-5][0-9]{2}$'
          then (r.source_evidence ->> 'statusCode')::integer else null end,
        'expectedPeriod', r.source_evidence ->> 'expectedPeriod',
        'actualPeriod', r.source_evidence ->> 'actualPeriod',
        'rowCount', case
          when coalesce(r.source_evidence ->> 'rowCount', r.source_evidence ->> 'rows', '') ~ '^[0-9]+$'
            then coalesce(r.source_evidence ->> 'rowCount', r.source_evidence ->> 'rows')::integer
          else null end
      )) as evidence
    from raw_diagnostics r
  ), classified as (
    select b.*,
      case
        when source_status in ('not-applicable', 'source-not-applicable') then 'not_applicable'
        when source_status = 'official-not-provided' then 'official_not_provided'
        when source_status in ('upstream-error', 'error', 'rate-limited') then 'upstream_error'
        when retryable then 'scheduled_repair'
        when source_status = 'insufficient-history' then 'insufficient_history'
        when source_status = 'stale-source-period' then 'stale_source'
        when source_status = 'empty-no-history' then 'unavailable_from_source'
        else 'partial_source'
      end as classification,
      case
        when source_status in ('not-applicable', 'source-not-applicable') then '此商品不適用該欄位，不列為缺漏'
        when source_status = 'official-not-provided' then '目前免費官方來源未提供此欄位，系統保留缺漏且不以 0 分代替'
        when source_status in ('upstream-error', 'error', 'rate-limited')
          then '上游 API 或來源暫時失敗，等待下次重試'
        when retryable then '資料可重試，已排入後端修復隊列'
        when source_status = 'insufficient-history' then '來源歷史筆數尚未達正式分析門檻'
        when source_status = 'stale-source-period' then '公開來源期別落後，等待官方更新'
        when source_status = 'empty-no-history' then 'API 已回應，但公開來源沒有該檔歷史資料'
        else '來源只提供部分欄位，系統不以 0 分代替'
      end as reason
    from base b
  ), summary as (
    select dataset_key, classification, count(*)::integer as count
    from classified
    group by dataset_key, classification
  ), dataset_payload as (
    select s.dataset_key, pg_catalog.jsonb_build_object(
      'total', sum(s.count),
      'retryable', (select count(*) from classified c where c.dataset_key = s.dataset_key and c.retryable),
      'classifications', pg_catalog.jsonb_object_agg(s.classification, s.count order by s.classification)
    ) as payload
    from summary s
    group by s.dataset_key
  ), examples as (
    select * from classified
    order by retryable desc, data_date desc nulls last, symbol, dataset_key
    limit greatest(1, least(coalesce(p_limit, 40), 100))
  )
  select pg_catalog.jsonb_build_object(
    'generatedAt', clock_timestamp(),
    'datasets', coalesce((select pg_catalog.jsonb_object_agg(dataset_key, payload) from dataset_payload), '{}'::jsonb),
    'summary', coalesce((select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
      'dataset', dataset_key,
      'classification', classification,
      'count', count
    ) order by dataset_key, classification) from summary), '[]'::jsonb),
    'examples', coalesce((select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
      'symbol', symbol,
      'name', name,
      'group', group_name,
      'dataDate', data_date,
      'dataset', dataset_key,
      'sourceStatus', source_status,
      'classification', classification,
      'retryable', retryable,
      'reasonCode', classification,
      'reason', reason,
      'evidence', evidence
    )) from examples), '[]'::jsonb)
  );
$$;

revoke all on function public.twss_public_missing_data(integer) from public;
grant execute on function public.twss_public_missing_data(integer)
  to anon, authenticated, service_role;

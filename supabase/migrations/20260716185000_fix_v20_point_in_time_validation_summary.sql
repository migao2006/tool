-- Correct the validation read model to enforce the same point-in-time
-- publication eligibility already used by immutable calibration.
--
-- A run published on/after the observed entry session was not actionable and
-- must never contribute to validation. When several revisions existed before
-- entry, only the last pre-entry revision is eligible.

create or replace function public.twss_v20_read_validation_summary(p_query jsonb default '{}'::jsonb)
returns jsonb
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
  v_model_key text := nullif(pg_catalog.btrim(coalesce(p_query ->> 'modelKey', '')), '');
  v_horizon_days integer := (p_query ->> 'horizonDays')::integer;
  v_model_version text := nullif(pg_catalog.btrim(coalesce(p_query ->> 'modelVersion', '')), '');
  v_strategy_key text := nullif(pg_catalog.btrim(coalesce(p_query ->> 'strategyKey', '')), '');
  v_market_regime text := nullif(pg_catalog.btrim(coalesce(p_query ->> 'marketRegime', '')), '');
  v_industry text := nullif(pg_catalog.btrim(coalesce(p_query ->> 'industry', '')), '');
  v_from_date date := (p_query ->> 'fromDate')::date;
  v_to_date date := (p_query ->> 'toDate')::date;
  v_top_n integer := least(
    greatest(coalesce((p_query ->> 'topN')::integer, 50), 1),
    500
  );
  v_minimum_sample_count integer := least(
    greatest(coalesce((p_query ->> 'minimumSampleCount')::integer, 100), 100),
    10000
  );
  v_sample_count integer;
  v_items jsonb;
begin
  if v_horizon_days = 60 then
    raise exception 'v20_research_horizon_not_public' using errcode = '22023';
  end if;

  if p_query is null
    or pg_catalog.jsonb_typeof(p_query) <> 'object'
    or (v_model_key is not null and v_model_key not in ('short', 'medium'))
    or (v_from_date is not null and v_to_date is not null and v_from_date > v_to_date)
    or (
      v_horizon_days is not null
      and not (
        (v_model_key = 'short' and v_horizon_days in (2, 3, 5, 10))
        or (v_model_key = 'medium' and v_horizon_days in (10, 20, 40))
        or (v_model_key is null and v_horizon_days in (2, 3, 5, 10, 20, 40))
      )
    )
  then
    raise exception 'v20_invalid_validation_query' using errcode = '22023';
  end if;

  with latest as (
    select
      o.*,
      pg_catalog.row_number() over (
        partition by o.recommendation_item_id, o.observed_horizon_days
        order by o.revision desc
      ) as observation_order
    from public.v20_outcome_observations o
  )
  select count(*)::integer
  into v_sample_count
  from latest o
  join public.v20_recommendation_items i on i.id = o.recommendation_item_id
  join public.v20_recommendation_runs r on r.id = i.run_id
  where o.observation_order = 1
    and r.status = 'published'
    and i.public_visible
    and i.is_eligible
    and i.rank_position between 1 and v_top_n
    and o.observed_horizon_days = i.horizon_days
    -- Only a recommendation actually available before the first session can
    -- enter point-in-time validation. If multiple same-day revisions existed
    -- before entry, keep only the last one that users could have observed.
    and r.published_at < pg_catalog.timezone('Asia/Taipei', o.entry_date::timestamp)
    and not exists (
      select 1
      from public.v20_recommendation_runs later
      where later.status = 'published'
        and later.data_date = r.data_date
        and later.model_version = r.model_version
        and later.revision > r.revision
        and later.published_at
          < pg_catalog.timezone('Asia/Taipei', o.entry_date::timestamp)
    )
    and (v_model_key is null or i.model_key = v_model_key)
    and (v_horizon_days is null or i.horizon_days = v_horizon_days)
    and (v_model_version is null or i.model_version = v_model_version)
    and (v_strategy_key is null or i.strategy_key = v_strategy_key)
    and (v_market_regime is null or coalesce(r.market_regime, 'unknown') = v_market_regime)
    and (v_industry is null or pg_catalog.lower(coalesce(i.industry, '')) = pg_catalog.lower(v_industry))
    and (v_from_date is null or r.data_date >= v_from_date)
    and (v_to_date is null or r.data_date <= v_to_date);

  if v_sample_count < v_minimum_sample_count then
    return pg_catalog.jsonb_build_object(
      'status', 'insufficient_data',
      'source', 'immutable_forward_observations',
      'sampleCount', v_sample_count,
      'minimumSampleCount', v_minimum_sample_count,
      'sufficient', false,
      'topN', v_top_n,
      'items', '[]'::jsonb
    );
  end if;

  with latest as (
    select
      o.*,
      pg_catalog.row_number() over (
        partition by o.recommendation_item_id, o.observed_horizon_days
        order by o.revision desc
      ) as observation_order
    from public.v20_outcome_observations o
  ), filtered as (
    select
      o.*,
      i.model_key,
      i.horizon_days,
      i.model_version,
      i.strategy_key,
      i.turnover_exposure,
      i.estimated_total_cost_pct,
      r.data_date,
      coalesce(r.market_regime, 'unknown') as market_regime
    from latest o
    join public.v20_recommendation_items i on i.id = o.recommendation_item_id
    join public.v20_recommendation_runs r on r.id = i.run_id
    where o.observation_order = 1
      and r.status = 'published'
      and i.public_visible
      and i.is_eligible
      and i.rank_position between 1 and v_top_n
      and o.observed_horizon_days = i.horizon_days
    -- Only a recommendation actually available before the first session can
    -- enter point-in-time validation. If multiple same-day revisions existed
    -- before entry, keep only the last one that users could have observed.
    and r.published_at < pg_catalog.timezone('Asia/Taipei', o.entry_date::timestamp)
    and not exists (
      select 1
      from public.v20_recommendation_runs later
      where later.status = 'published'
        and later.data_date = r.data_date
        and later.model_version = r.model_version
        and later.revision > r.revision
        and later.published_at
          < pg_catalog.timezone('Asia/Taipei', o.entry_date::timestamp)
    )
      and (v_model_key is null or i.model_key = v_model_key)
      and (v_horizon_days is null or i.horizon_days = v_horizon_days)
      and (v_model_version is null or i.model_version = v_model_version)
      and (v_strategy_key is null or i.strategy_key = v_strategy_key)
      and (v_market_regime is null or coalesce(r.market_regime, 'unknown') = v_market_regime)
      and (v_industry is null or pg_catalog.lower(coalesce(i.industry, '')) = pg_catalog.lower(v_industry))
      and (v_from_date is null or r.data_date >= v_from_date)
      and (v_to_date is null or r.data_date <= v_to_date)
  ), buckets as (
    select
      f.model_key,
      f.horizon_days,
      f.model_version,
      f.strategy_key,
      f.market_regime,
      count(*)::integer as sample_count,
      pg_catalog.round((100 * avg(case when f.net_return > 0 then 1 else 0 end))::numeric, 2)
        as cost_after_win_rate,
      pg_catalog.round((100 * avg(case when f.excess_return_net > 0 then 1 else 0 end))::numeric, 2)
        as excess_win_rate,
      pg_catalog.round(avg(f.gross_return)::numeric, 4) as average_gross_return,
      pg_catalog.round(avg(f.net_return)::numeric, 4) as average_net_return,
      pg_catalog.round(avg(f.excess_return_net)::numeric, 4) as average_excess_return_net,
      pg_catalog.round(
        (pg_catalog.percentile_cont(0.5) within group (order by f.net_return))::numeric,
        4
      ) as median_net_return,
      pg_catalog.round(
        (pg_catalog.percentile_cont(0.1) within group (order by f.net_return))::numeric,
        4
      ) as return_p10,
      pg_catalog.round(
        (pg_catalog.percentile_cont(0.9) within group (order by f.net_return))::numeric,
        4
      ) as return_p90,
      pg_catalog.round(avg(f.mfe)::numeric, 4) as average_mfe,
      pg_catalog.round(avg(f.mae)::numeric, 4) as average_mae,
      pg_catalog.round(avg(f.transaction_cost)::numeric, 4) as average_realized_cost,
      pg_catalog.round(avg(f.estimated_total_cost_pct)::numeric, 4) as average_estimated_cost,
      pg_catalog.round(avg(f.turnover_exposure)::numeric, 4) as average_turnover_exposure,
      pg_catalog.round(
        (
          avg(f.net_return)
          - 1.96 * coalesce(pg_catalog.stddev_samp(f.net_return), 0)
            / pg_catalog.sqrt(count(*)::numeric)
        )::numeric,
        4
      ) as mean_net_return_ci95_low,
      pg_catalog.round(
        (
          avg(f.net_return)
          + 1.96 * coalesce(pg_catalog.stddev_samp(f.net_return), 0)
            / pg_catalog.sqrt(count(*)::numeric)
        )::numeric,
        4
      ) as mean_net_return_ci95_high,
      min(f.data_date) as first_data_date,
      max(f.data_date) as last_data_date,
      max(f.observed_at) as generated_at
    from filtered f
    group by f.model_key, f.horizon_days, f.model_version, f.strategy_key, f.market_regime
    having count(*) >= v_minimum_sample_count
  ), cohort_returns as (
    -- A cohort is one publication date's equal-weight top-N realized result.
    -- This is intentionally labelled as a realized-cohort curve: the stored
    -- endpoint observations cannot reconstruct daily mark-to-market portfolio
    -- equity and must not be presented as such.
    select
      f.model_key,
      f.horizon_days,
      f.model_version,
      f.strategy_key,
      f.market_regime,
      f.data_date,
      avg(f.net_return)::numeric as cohort_net_return
    from filtered f
    group by
      f.model_key,
      f.horizon_days,
      f.model_version,
      f.strategy_key,
      f.market_regime,
      f.data_date
  ), cohort_equity as (
    select
      c.*,
      pg_catalog.exp(
        sum(
          pg_catalog.ln(
            greatest(0.000001::numeric, 1::numeric + c.cohort_net_return / 100::numeric)
          )
        ) over (
          partition by c.model_key, c.horizon_days, c.model_version, c.strategy_key, c.market_regime
          order by c.data_date
          rows between unbounded preceding and current row
        )
      )::numeric as equity
    from cohort_returns c
  ), cohort_peaks as (
    select
      e.*,
      greatest(
        1::numeric,
        max(e.equity) over (
          partition by e.model_key, e.horizon_days, e.model_version, e.strategy_key, e.market_regime
          order by e.data_date
          rows between unbounded preceding and current row
        )
      ) as peak_equity
    from cohort_equity e
  ), bucket_drawdowns as (
    select
      p.model_key,
      p.horizon_days,
      p.model_version,
      p.strategy_key,
      p.market_regime,
      pg_catalog.round(
        pg_catalog.abs(
          least(
            0::numeric,
            min(100::numeric * (p.equity / nullif(p.peak_equity, 0) - 1::numeric))
          )
        ),
        4
      ) as max_realized_cohort_drawdown
    from cohort_peaks p
    group by p.model_key, p.horizon_days, p.model_version, p.strategy_key, p.market_regime
  )
  select coalesce(
    pg_catalog.jsonb_agg(
      pg_catalog.jsonb_build_object(
        'modelKey', b.model_key,
        'horizonDays', b.horizon_days,
        'modelVersion', b.model_version,
        'strategyKey', b.strategy_key,
        'marketRegime', b.market_regime,
        'sampleCount', b.sample_count,
        'costAfterWinRate', b.cost_after_win_rate,
        'excessWinRate', b.excess_win_rate,
        'averageGrossReturn', b.average_gross_return,
        'averageNetReturn', b.average_net_return,
        'averageExcessReturnNet', b.average_excess_return_net,
        'medianNetReturn', b.median_net_return,
        'returnP10', b.return_p10,
        'returnP90', b.return_p90,
        'averageMfe', b.average_mfe,
        'averageMae', b.average_mae,
        'averageRealizedCost', b.average_realized_cost,
        'averageEstimatedCost', b.average_estimated_cost,
        'averageTurnoverExposure', b.average_turnover_exposure,
        'maxRealizedCohortDrawdown', d.max_realized_cohort_drawdown,
        'meanNetReturnCi95Low', b.mean_net_return_ci95_low,
        'meanNetReturnCi95High', b.mean_net_return_ci95_high,
        'firstDataDate', b.first_data_date,
        'lastDataDate', b.last_data_date,
        'generatedAt', b.generated_at
      )
      order by b.model_key, b.horizon_days, b.model_version, b.strategy_key, b.market_regime
    ),
    '[]'::jsonb
  ) into v_items
  from buckets b
  left join bucket_drawdowns d
    on d.model_key = b.model_key
    and d.horizon_days = b.horizon_days
    and d.model_version = b.model_version
    and d.strategy_key = b.strategy_key
    and d.market_regime = b.market_regime;

  if pg_catalog.jsonb_array_length(v_items) = 0 then
    return pg_catalog.jsonb_build_object(
      'status', 'insufficient_data',
      'source', 'immutable_forward_observations',
      'sampleCount', v_sample_count,
      'minimumSampleCount', v_minimum_sample_count,
      'sufficient', false,
      'topN', v_top_n,
      'items', '[]'::jsonb
    );
  end if;

  return pg_catalog.jsonb_build_object(
    'status', 'ready',
    'source', 'immutable_forward_observations',
    'sampleCount', v_sample_count,
    'minimumSampleCount', v_minimum_sample_count,
    'sufficient', true,
    'topN', v_top_n,
    'items', v_items
  );
end;
$$;

revoke all on function public.twss_v20_read_validation_summary(jsonb)
  from public, anon, authenticated, service_role;
grant execute on function public.twss_v20_read_validation_summary(jsonb)
  to service_role;

comment on function public.twss_v20_read_validation_summary(jsonb) is
  'Service-only point-in-time validation read model. It uses latest immutable outcome revisions, excludes runs published on/after entry, and keeps only the last same-day revision available before entry.';

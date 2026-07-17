-- Read-only 2-8 week composite over an immutable published recommendation run.
-- The blend is intentionally derived at read time so published source items are
-- never rewritten and a newer model can only appear through a new publication.
create or replace function public.twss_v20_read_medium_blend(p_query jsonb default '{}'::jsonb)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  v_group_name text := nullif(pg_catalog.btrim(coalesce(p_query ->> 'groupName', '')), '');
  v_industry text := nullif(pg_catalog.btrim(coalesce(p_query ->> 'industry', '')), '');
  v_limit integer := least(greatest(coalesce((p_query ->> 'limit')::integer, 50), 1), 200);
  v_after_rank integer := greatest(coalesce((p_query ->> 'afterRank')::integer, 0), 0);
  v_run_id bigint := (p_query ->> 'runId')::bigint;
  v_run public.v20_recommendation_runs%rowtype;
  v_total integer;
  v_remaining_count integer;
  v_page_count integer;
  v_next_after_rank integer;
  v_items jsonb;
begin
  if p_query is null or pg_catalog.jsonb_typeof(p_query) <> 'object'
    or (v_group_name is not null and v_group_name not in ('listed', 'otc', 'etf'))
  then
    raise exception 'v20_invalid_medium_blend_query' using errcode = '22023';
  end if;

  if v_run_id is null then
    select h.run_id into v_run_id
    from public.v20_publication_head h
    where h.audience = 'public';
  end if;

  select * into v_run
  from public.v20_recommendation_runs r
  where r.id = v_run_id and r.status = 'published';

  if not found then
    return pg_catalog.jsonb_build_object(
      'run', null,
      'items', '[]'::jsonb,
      'total', 0,
      'pageCount', 0,
      'hasMore', false,
      'nextAfterRank', null
    );
  end if;

  with components as (
    select
      i.*,
      case i.horizon_days when 10 then 0.25 when 20 then 0.50 when 40 then 0.25 end weight
    from public.v20_recommendation_items i
    where i.run_id = v_run_id
      and i.model_key = 'medium'
      and i.horizon_days in (10, 20, 40)
      and i.public_visible
      and not i.research_only
      and i.is_eligible
      and i.rank_position is not null
  ), blended as (
    select
      c.run_id,
      c.symbol,
      (pg_catalog.array_agg(c.name order by case c.horizon_days when 20 then 0 when 10 then 1 else 2 end))[1] name,
      pg_catalog.max(c.signal_date) signal_date,
      (pg_catalog.array_agg(c.model_version order by case c.horizon_days when 20 then 0 when 10 then 1 else 2 end))[1] model_version,
      (pg_catalog.array_agg(c.group_name order by case c.horizon_days when 20 then 0 when 10 then 1 else 2 end))[1] group_name,
      (pg_catalog.array_agg(c.market order by case c.horizon_days when 20 then 0 when 10 then 1 else 2 end))[1] market,
      (pg_catalog.array_agg(c.industry order by case c.horizon_days when 20 then 0 when 10 then 1 else 2 end))[1] industry,
      (pg_catalog.array_agg(c.instrument_type order by case c.horizon_days when 20 then 0 when 10 then 1 else 2 end))[1] instrument_type,
      pg_catalog.round(pg_catalog.sum(c.raw_opportunity_score * c.weight), 4) raw_opportunity_score,
      pg_catalog.round(pg_catalog.sum(c.net_opportunity_score * c.weight), 4) net_opportunity_score,
      pg_catalog.max(c.risk_score) risk_score,
      pg_catalog.min(c.confidence) confidence,
      pg_catalog.min(c.completeness) completeness,
      pg_catalog.round(pg_catalog.sum(c.estimated_commission_pct * c.weight), 4) estimated_commission_pct,
      pg_catalog.round(pg_catalog.sum(c.estimated_tax_pct * c.weight), 4) estimated_tax_pct,
      pg_catalog.round(pg_catalog.sum(c.estimated_slippage_pct * c.weight), 4) estimated_slippage_pct,
      pg_catalog.round(pg_catalog.sum(c.estimated_spread_pct * c.weight), 4) estimated_spread_pct,
      pg_catalog.round(pg_catalog.sum(c.estimated_total_cost_pct * c.weight), 4) estimated_total_cost_pct,
      pg_catalog.round(pg_catalog.sum(c.downside_penalty_score * c.weight), 4) downside_penalty_score,
      pg_catalog.round(pg_catalog.sum(c.turnover_penalty_score * c.weight), 4) turnover_penalty_score,
      pg_catalog.round(pg_catalog.sum(c.cost_penalty_score * c.weight), 4) cost_penalty_score,
      pg_catalog.round(pg_catalog.sum(c.turnover_exposure * c.weight), 4) turnover_exposure,
      (pg_catalog.array_agg(c.liquidity_grade order by case c.horizon_days when 20 then 0 when 10 then 1 else 2 end))[1] liquidity_grade,
      (pg_catalog.array_agg(c.opportunity_state order by case c.horizon_days when 20 then 0 when 10 then 1 else 2 end))[1] opportunity_state,
      pg_catalog.min(c.calibration_sample_count) calibration_sample_count,
      (pg_catalog.array_agg(c.benchmark_key order by case c.horizon_days when 20 then 0 when 10 then 1 else 2 end))[1] benchmark_key,
      (pg_catalog.array_agg(c.recommended_holding_days order by case c.horizon_days when 20 then 0 when 10 then 1 else 2 end))[1] recommended_holding_days,
      (pg_catalog.array_agg(c.recommended_action order by case c.horizon_days when 20 then 0 when 10 then 1 else 2 end))[1] recommended_action,
      (pg_catalog.array_agg(c.reasons order by case c.horizon_days when 20 then 0 when 10 then 1 else 2 end))[1] reasons,
      (pg_catalog.array_agg(c.risks order by case c.horizon_days when 20 then 0 when 10 then 1 else 2 end))[1] risks,
      (pg_catalog.array_agg(c.invalidation_conditions order by case c.horizon_days when 20 then 0 when 10 then 1 else 2 end))[1] invalidation_conditions,
      (pg_catalog.array_agg(c.source_manifest order by case c.horizon_days when 20 then 0 when 10 then 1 else 2 end))[1]
        || pg_catalog.jsonb_build_object('blendSource', 'immutable_medium_10_20_40') source_manifest,
      pg_catalog.jsonb_object_agg(
        c.horizon_days::text,
        pg_catalog.jsonb_build_object(
          'rawOpportunityScore', c.raw_opportunity_score,
          'netOpportunityScore', c.net_opportunity_score,
          'riskScore', c.risk_score,
          'confidence', c.confidence,
          'completeness', c.completeness,
          'rank', c.rank_position
        ) order by c.horizon_days
      ) component_horizons
    from components c
    group by c.run_id, c.symbol
    having pg_catalog.count(*) = 3
      and pg_catalog.count(distinct c.horizon_days) = 3
  ), ranked as (
    select
      b.*,
      pg_catalog.row_number() over (
        order by b.net_opportunity_score desc, b.risk_score asc, b.symbol asc
      )::integer blend_rank,
      pg_catalog.count(*) over ()::integer universe_count
    from blended b
  ), matching as (
    select *
    from ranked r
    where (v_group_name is null or r.group_name = v_group_name)
      and (v_industry is null or pg_catalog.lower(coalesce(r.industry, '')) = pg_catalog.lower(v_industry))
  ), filtered as (
    select * from matching where blend_rank > v_after_rank
  ), page as (
    select * from filtered order by blend_rank limit v_limit
  )
  select
    (select pg_catalog.count(*)::integer from matching),
    (select pg_catalog.count(*)::integer from filtered),
    (select pg_catalog.count(*)::integer from page),
    (select pg_catalog.max(blend_rank)::integer from page),
    coalesce((
      select pg_catalog.jsonb_agg(
        pg_catalog.jsonb_build_object(
          'symbol', p.symbol,
          'name', p.name,
          'signalDate', p.signal_date,
          'modelKey', 'medium',
          'horizonDays', 'blend',
          'modelVersion', p.model_version,
          'groupName', p.group_name,
          'market', p.market,
          'industry', p.industry,
          'instrumentType', p.instrument_type,
          'strategyKey', 'medium_blend',
          'isEligible', true,
          'publicVisible', true,
          'researchOnly', false,
          'rankPosition', p.blend_rank,
          'previousRank', null,
          'rankDelta', null,
          'marketPercentile', pg_catalog.round(100.0 * (p.universe_count - p.blend_rank + 1) / p.universe_count, 4),
          'rawOpportunityScore', p.raw_opportunity_score,
          'netOpportunityScore', p.net_opportunity_score,
          'opportunityScore', p.net_opportunity_score,
          'riskScore', p.risk_score,
          'confidence', p.confidence,
          'completeness', p.completeness,
          'componentHorizons', p.component_horizons,
          'blendWeights', '{"10":0.25,"20":0.50,"40":0.25}'::jsonb
        ) || pg_catalog.jsonb_build_object(
          'estimatedCommissionPct', p.estimated_commission_pct,
          'estimatedTaxPct', p.estimated_tax_pct,
          'estimatedSlippagePct', p.estimated_slippage_pct,
          'estimatedSpreadPct', p.estimated_spread_pct,
          'estimatedTotalCostPct', p.estimated_total_cost_pct,
          'downsidePenaltyScore', p.downside_penalty_score,
          'turnoverPenaltyScore', p.turnover_penalty_score,
          'costPenaltyScore', p.cost_penalty_score,
          'turnoverExposure', p.turnover_exposure,
          'liquidityGrade', p.liquidity_grade,
          'opportunityState', p.opportunity_state,
          'predictionBasis', 'deterministic-medium-blend',
          'calibrationSampleCount', p.calibration_sample_count,
          'benchmarkKey', p.benchmark_key,
          'recommendedHoldingDays', p.recommended_holding_days,
          'recommendedAction', p.recommended_action,
          'featureScores', pg_catalog.jsonb_build_object('blend', true),
          'gateResults', pg_catalog.jsonb_build_object('allComponentHorizonsPassed', true),
          'reasons', p.reasons,
          'risks', p.risks,
          'invalidationConditions', p.invalidation_conditions,
          'sourceManifest', p.source_manifest
        ) order by p.blend_rank
      ) from page p
    ), '[]'::jsonb)
  into v_total, v_remaining_count, v_page_count, v_next_after_rank, v_items;

  return pg_catalog.jsonb_build_object(
    'run', pg_catalog.jsonb_build_object(
      'runId', v_run.id,
      'dataDate', v_run.data_date,
      'dataCutoffAt', v_run.data_cutoff_at,
      'revision', v_run.revision,
      'modelVersion', v_run.model_version,
      'featureVersion', v_run.feature_version,
      'costModelVersion', v_run.cost_model_version,
      'calibrationVersion', v_run.calibration_version,
      'sourceVersion', v_run.source_version,
      'sourceHash', v_run.source_hash,
      'contentHash', v_run.content_hash,
      'marketRegime', v_run.market_regime,
      'publishedAt', v_run.published_at
    ),
    'items', v_items,
    'total', v_total,
    'pageCount', v_page_count,
    'hasMore', v_remaining_count > v_page_count,
    'nextAfterRank', v_next_after_rank,
    'order', 'net_opportunity_score.desc,risk_score.asc,symbol.asc',
    'blendWeights', '{"10":0.25,"20":0.50,"40":0.25}'::jsonb
  );
end;
$$;

revoke all on function public.twss_v20_read_medium_blend(jsonb)
  from public, anon, authenticated, service_role;
grant execute on function public.twss_v20_read_medium_blend(jsonb)
  to anon, authenticated, service_role;

comment on function public.twss_v20_read_medium_blend(jsonb) is
  'Public immutable medium ranking blend. Requires eligible public 10/20/40-day items and exposes only a bounded keyset-paginated read model.';

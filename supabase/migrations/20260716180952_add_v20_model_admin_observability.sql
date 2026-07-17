-- Register the transparent v20.1 rules as the initial structural baseline.
-- This is not a performance claim: immutable forward outcomes must reach the
-- published sample threshold before any performance metrics may be shown.
do $$
declare
  v_model_key text;
  v_release_id bigint;
begin
  foreach v_model_key in array array['short'::text, 'medium'::text]
  loop
    v_release_id := public.twss_v20_register_model_release(
      pg_catalog.jsonb_build_object(
        'modelKey', v_model_key,
        'modelVersion', '20.1',
        'artifactHash', '5dd573115b8695b420af989c3ed21679afba35a57b79306007c639c92ade5292',
        'featureVersion', 'v20.1-separated-engines',
        'costModelVersion', 'tw-market-cost-2026-07',
        'validationStatus', 'passed',
        'configuration', pg_catalog.jsonb_build_object(
          'engine', 'transparent_rule_baseline',
          'publicHorizons', case
            when v_model_key = 'short' then pg_catalog.to_jsonb(array[2, 3, 5, 10])
            else pg_catalog.to_jsonb(array[10, 20, 40])
          end,
          'researchHorizons', case
            when v_model_key = 'medium' then pg_catalog.to_jsonb(array[60])
            else '[]'::jsonb
          end
        ),
        'validationMetrics', pg_catalog.jsonb_build_object(
          'validationKind', 'structural_baseline',
          'structuralStatus', 'passed',
          'performanceStatus', 'collecting',
          'performanceMetricsAvailable', false,
          'sampleCount', 0,
          'minimumSampleCount', 100
        ),
        'validationNotes',
          'Structural baseline only. Forward performance remains collecting and is not asserted.',
        'registeredBy', 'migration:20260716180952'
      )
    );

    -- Never replace an operator-selected champion. Only fill an empty channel,
    -- and never place one release in both channels.
    if not exists (
      select 1
      from public.v20_model_channel_heads h
      where h.model_key = v_model_key
        and h.channel = 'champion'
    ) and not exists (
      select 1
      from public.v20_model_channel_heads h
      where h.model_key = v_model_key
        and h.release_id = v_release_id
    ) and exists (
      select 1
      from public.v20_model_releases r
      where r.id = v_release_id
        and r.validation_status = 'passed'
    ) then
      perform public.twss_v20_set_model_channel(
        pg_catalog.jsonb_build_object(
          'modelKey', v_model_key,
          'channel', 'champion',
          'releaseId', v_release_id,
          'reason',
            'Initial transparent-rule structural baseline; forward performance is still collecting.',
          'changedBy', 'migration:20260716180952'
        )
      );
    end if;
  end loop;
end
$$;

-- Keep the prior operations payload as a service-only implementation detail.
-- The public name remains the single authenticated administrator RPC.
do $$
begin
  if pg_catalog.to_regprocedure('public.twss_admin_operations_log_v210_base(integer)') is null then
    alter function public.twss_admin_operations_log(integer)
      rename to twss_admin_operations_log_v210_base;
  end if;
end
$$;

revoke all on function public.twss_admin_operations_log_v210_base(integer)
  from public, anon, authenticated;
grant execute on function public.twss_admin_operations_log_v210_base(integer)
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
  v_run_id bigint;
  v_current_publication jsonb;
  v_channels jsonb := pg_catalog.jsonb_build_object(
    'short', pg_catalog.jsonb_build_object('champion', null, 'challenger', null),
    'medium', pg_catalog.jsonb_build_object('champion', null, 'challenger', null)
  );
  v_recent_validations jsonb := '[]'::jsonb;
  v_runtime_by_model jsonb := '{}'::jsonb;
  v_validation jsonb := '{}'::jsonb;
  v_rank_changes jsonb := '{}'::jsonb;
  v_anomalies jsonb := '{}'::jsonb;
begin
  if (select auth.uid()) is null or not (select public.twss_is_admin()) then
    raise exception using errcode = '42501', message = 'admin_required';
  end if;

  v_payload := public.twss_admin_operations_log_v210_base(v_limit);

  select
    r.id,
    pg_catalog.jsonb_build_object(
      'available', true,
      'runId', r.id,
      'publicationKey', r.publication_key,
      'dataDate', r.data_date,
      'dataCutoffAt', r.data_cutoff_at,
      'revision', r.revision,
      'modelVersion', r.model_version,
      'featureVersion', r.feature_version,
      'costModelVersion', r.cost_model_version,
      'calibrationVersion', r.calibration_version,
      'marketRegime', r.market_regime,
      'expectedSymbolCount', r.expected_symbol_count,
      'scoredSymbolCount', r.scored_symbol_count,
      'cycleCompletenessPct', r.cycle_completeness,
      'publicItemCount', r.signal_count - r.research_item_count,
      'expectedPublicItemCount', r.expected_symbol_count * 7,
      'publicItemCoveragePct', case
        when r.expected_symbol_count <= 0 then 0
        else pg_catalog.round(
          (100 * (r.signal_count - r.research_item_count)::numeric)
            / (r.expected_symbol_count * 7)::numeric,
          2
        )
      end,
      'eligibleItemCount', r.eligible_item_count,
      'researchItemCount', r.research_item_count,
      'publishedAt', r.published_at,
      'contentHash', r.content_hash
    )
  into v_run_id, v_current_publication
  from public.v20_publication_head h
  join public.v20_recommendation_runs r on r.id = h.run_id
  where h.audience = 'public'
    and r.status = 'published';

  if v_run_id is null then
    v_current_publication := pg_catalog.jsonb_build_object(
      'available', false,
      'status', 'awaiting_first_immutable_publication'
    );
  end if;

  with model_keys(model_key) as (
    values ('short'::text), ('medium'::text)
  ), channel_keys(channel) as (
    values ('champion'::text), ('challenger'::text)
  ), latest_validation as (
    select distinct on (e.release_id)
      e.id,
      e.release_id,
      e.validation_status,
      e.window_start,
      e.window_end,
      e.notes,
      e.recorded_at
    from public.v20_model_validation_events e
    order by e.release_id, e.recorded_at desc, e.id desc
  ), slots as (
    select
      m.model_key,
      c.channel,
      case when r.id is null then null else pg_catalog.jsonb_build_object(
        'releaseId', r.id,
        'modelVersion', r.model_version,
        'artifactHash', r.artifact_hash,
        'featureVersion', r.feature_version,
        'costModelVersion', r.cost_model_version,
        'calibrationVersion', r.calibration_version,
        'validationStatus', r.validation_status,
        'performanceStatus', 'collecting',
        'performanceMetricsAvailable', false,
        'registeredAt', r.registered_at,
        'changedAt', h.changed_at,
        'latestValidation', case when lv.id is null then null
          else pg_catalog.jsonb_build_object(
            'eventId', lv.id,
            'status', lv.validation_status,
            'windowStart', lv.window_start,
            'windowEnd', lv.window_end,
            'notes', lv.notes,
            'recordedAt', lv.recorded_at
          )
        end
      ) end as release_payload
    from model_keys m
    cross join channel_keys c
    left join public.v20_model_channel_heads h
      on h.model_key = m.model_key
     and h.channel = c.channel
    left join public.v20_model_releases r on r.id = h.release_id
    left join latest_validation lv on lv.release_id = r.id
  ), by_model as (
    select
      s.model_key,
      pg_catalog.jsonb_object_agg(s.channel, s.release_payload order by s.channel) as payload
    from slots s
    group by s.model_key
  )
  select coalesce(
    pg_catalog.jsonb_object_agg(m.model_key, m.payload order by m.model_key),
    v_channels
  )
  into v_channels
  from by_model m;

  select coalesce(
    pg_catalog.jsonb_agg(
      pg_catalog.jsonb_build_object(
        'eventId', e.id,
        'releaseId', e.release_id,
        'modelKey', e.model_key,
        'modelVersion', e.model_version,
        'validationStatus', e.validation_status,
        'performanceStatus', 'collecting',
        'performanceMetricsAvailable', false,
        'windowStart', e.window_start,
        'windowEnd', e.window_end,
        'notes', e.notes,
        'recordedAt', e.recorded_at
      ) order by e.recorded_at desc, e.id desc
    ),
    '[]'::jsonb
  )
  into v_recent_validations
  from (
    select
      ve.id,
      ve.release_id,
      r.model_key,
      r.model_version,
      ve.validation_status,
      ve.window_start,
      ve.window_end,
      ve.notes,
      ve.recorded_at
    from public.v20_model_validation_events ve
    join public.v20_model_releases r on r.id = ve.release_id
    order by ve.recorded_at desc, ve.id desc
    limit 10
  ) e;

  with model_keys(model_key) as (
    values ('short'::text), ('medium'::text)
  ), runtime as (
    select
      i.model_key,
      pg_catalog.count(*)::integer as opportunity_count,
      pg_catalog.count(distinct i.symbol)::integer as symbol_count,
      pg_catalog.round(pg_catalog.avg(i.completeness)::numeric, 2)
        as average_completeness,
      pg_catalog.round(pg_catalog.avg(i.estimated_total_cost_pct)::numeric, 4)
        as average_cost,
      pg_catalog.round(pg_catalog.avg(i.turnover_exposure)::numeric, 4)
        as average_turnover,
      pg_catalog.count(*) filter (where i.rank_delta is not null)::integer
        as rank_compared_count,
      pg_catalog.round((
        pg_catalog.avg(pg_catalog.abs(i.rank_delta))
          filter (where i.rank_delta is not null)
      )::numeric, 2)
        as average_absolute_rank_change,
      pg_catalog.count(distinct i.symbol) filter (
        where i.completeness < 80
          or i.benchmark_key is null
          or (
            i.calibrated_up_probability is not null
            and (
              coalesce(i.calibration_sample_count, 0) < 100
              or i.prediction_basis not ilike '%calibrat%'
            )
          )
          or (
            i.rank_delta is not null
            and (
              i.previous_rank is null
              or i.rank_position is null
              or i.rank_delta <> i.previous_rank - i.rank_position
            )
          )
      )::integer as anomaly_symbol_count
    from public.v20_recommendation_items i
    where i.run_id = v_run_id
      and i.public_visible
      and i.is_eligible
      and i.rank_position is not null
    group by i.model_key
  ), normalized as (
    select
      m.model_key,
      pg_catalog.jsonb_build_object(
        'opportunityCount', coalesce(r.opportunity_count, 0),
        'symbolCount', coalesce(r.symbol_count, 0),
        'averageCompletenessPct', r.average_completeness,
        'averageEstimatedCostPct', r.average_cost,
        'averageTurnoverProxy', r.average_turnover,
        'rankComparedCount', coalesce(r.rank_compared_count, 0),
        'averageAbsoluteRankChange', r.average_absolute_rank_change,
        'anomalySymbolCount', coalesce(r.anomaly_symbol_count, 0)
      ) as payload
    from model_keys m
    left join runtime r using (model_key)
  )
  select coalesce(
    pg_catalog.jsonb_object_agg(n.model_key, n.payload order by n.model_key),
    '{}'::jsonb
  )
  into v_runtime_by_model
  from normalized n;

  with latest_observations as (
    select distinct on (o.recommendation_item_id, o.observed_horizon_days)
      o.recommendation_item_id,
      o.observed_horizon_days,
      o.observed_at
    from public.v20_outcome_observations o
    order by o.recommendation_item_id, o.observed_horizon_days, o.revision desc
  ), model_keys(model_key) as (
    values ('short'::text), ('medium'::text)
  ), historical as (
    select
      i.model_key,
      pg_catalog.count(*)::integer as sample_count,
      pg_catalog.max(o.observed_at) as latest_observed_at
    from latest_observations o
    join public.v20_recommendation_items i on i.id = o.recommendation_item_id
    where i.public_visible
      and i.is_eligible
      and o.observed_horizon_days = i.horizon_days
    group by i.model_key
  ), current_run as (
    select
      i.model_key,
      pg_catalog.count(*)::integer as eligible_count,
      pg_catalog.count(o.recommendation_item_id)::integer as observed_count
    from public.v20_recommendation_items i
    left join latest_observations o
      on o.recommendation_item_id = i.id
     and o.observed_horizon_days = i.horizon_days
    where i.run_id = v_run_id
      and i.public_visible
      and i.is_eligible
      and i.rank_position is not null
    group by i.model_key
  ), normalized as (
    select
      m.model_key,
      coalesce(h.sample_count, 0) as sample_count,
      h.latest_observed_at,
      coalesce(c.eligible_count, 0) as eligible_count,
      coalesce(c.observed_count, 0) as observed_count,
      greatest(coalesce(c.eligible_count, 0) - coalesce(c.observed_count, 0), 0)
        as pending_count
    from model_keys m
    left join historical h using (model_key)
    left join current_run c using (model_key)
  )
  select pg_catalog.jsonb_build_object(
    'performanceStatus', 'collecting',
    'performanceMetricsAvailable', false,
    'minimumSampleCount', 100,
    'sampleCount', coalesce(pg_catalog.sum(n.sample_count), 0),
    'currentRunEligibleCount', coalesce(pg_catalog.sum(n.eligible_count), 0),
    'currentRunObservedCount', coalesce(pg_catalog.sum(n.observed_count), 0),
    'pendingOutcomeCount', coalesce(pg_catalog.sum(n.pending_count), 0),
    'latestObservedAt', pg_catalog.max(n.latest_observed_at),
    'byModel', coalesce(
      pg_catalog.jsonb_object_agg(
        n.model_key,
        pg_catalog.jsonb_build_object(
          'performanceStatus', 'collecting',
          'performanceMetricsAvailable', false,
          'minimumSampleCount', 100,
          'sampleCount', n.sample_count,
          'currentRunEligibleCount', n.eligible_count,
          'currentRunObservedCount', n.observed_count,
          'pendingOutcomeCount', n.pending_count,
          'latestObservedAt', n.latest_observed_at
        ) order by n.model_key
      ),
      '{}'::jsonb
    )
  )
  into v_validation
  from normalized n;

  select pg_catalog.jsonb_build_object(
    'available', pg_catalog.count(*) filter (where i.rank_delta is not null) > 0,
    'basis', 'previous_immutable_rank',
    'comparedCount', pg_catalog.count(*) filter (where i.rank_delta is not null),
    'improvedCount', pg_catalog.count(*) filter (where i.rank_delta > 0),
    'weakenedCount', pg_catalog.count(*) filter (where i.rank_delta < 0),
    'unchangedCount', pg_catalog.count(*) filter (where i.rank_delta = 0),
    'averageAbsoluteChange', pg_catalog.round(
      (
        pg_catalog.avg(pg_catalog.abs(i.rank_delta))
          filter (where i.rank_delta is not null)
      )::numeric,
      2
    ),
    'maximumAbsoluteChange', pg_catalog.max(pg_catalog.abs(i.rank_delta))
      filter (where i.rank_delta is not null),
    'largestChanges', coalesce((
      select pg_catalog.jsonb_agg(
        pg_catalog.jsonb_build_object(
          'symbol', changed.symbol,
          'name', changed.name,
          'modelKey', changed.model_key,
          'horizonDays', changed.horizon_days,
          'rankPosition', changed.rank_position,
          'previousRank', changed.previous_rank,
          'rankDelta', changed.rank_delta
        ) order by pg_catalog.abs(changed.rank_delta) desc,
          changed.model_key,
          changed.horizon_days,
          changed.symbol
      )
      from (
        select
          x.symbol,
          x.name,
          x.model_key,
          x.horizon_days,
          x.rank_position,
          x.previous_rank,
          x.rank_delta
        from public.v20_recommendation_items x
        where x.run_id = v_run_id
          and x.public_visible
          and x.is_eligible
          and x.rank_delta is not null
        order by pg_catalog.abs(x.rank_delta) desc,
          x.model_key,
          x.horizon_days,
          x.symbol
        limit 10
      ) changed
    ), '[]'::jsonb)
  )
  into v_rank_changes
  from public.v20_recommendation_items i
  where i.run_id = v_run_id
    and i.public_visible
    and i.is_eligible
    and i.rank_position is not null;

  select pg_catalog.jsonb_build_object(
    'symbolCount', pg_catalog.count(distinct i.symbol) filter (
      where i.completeness < 80
        or i.benchmark_key is null
        or (
          i.calibrated_up_probability is not null
          and (
            coalesce(i.calibration_sample_count, 0) < 100
            or i.prediction_basis not ilike '%calibrat%'
          )
        )
        or (
          i.rank_delta is not null
          and (
            i.previous_rank is null
            or i.rank_position is null
            or i.rank_delta <> i.previous_rank - i.rank_position
          )
        )
    ),
    'lowCompletenessCount', pg_catalog.count(*) filter (where i.completeness < 80),
    'missingBenchmarkCount', pg_catalog.count(*) filter (where i.benchmark_key is null),
    'invalidCalibrationClaimCount', pg_catalog.count(*) filter (
      where i.calibrated_up_probability is not null
        and (
          coalesce(i.calibration_sample_count, 0) < 100
          or i.prediction_basis not ilike '%calibrat%'
        )
    ),
    'inconsistentRankDeltaCount', pg_catalog.count(*) filter (
      where i.rank_delta is not null
        and (
          i.previous_rank is null
          or i.rank_position is null
          or i.rank_delta <> i.previous_rank - i.rank_position
        )
    )
  )
  into v_anomalies
  from public.v20_recommendation_items i
  where i.run_id = v_run_id
    and i.public_visible
    and i.is_eligible
    and i.rank_position is not null;

  return v_payload || pg_catalog.jsonb_build_object(
    'version', '20.1.0',
    'calibrationReadiness', coalesce(v_payload -> 'calibrationReadiness', '{}'::jsonb)
      || pg_catalog.jsonb_build_object(
        'ready', false,
        'thresholds', pg_catalog.jsonb_build_object('exact', 100, 'fallback', 150),
        'byModel', pg_catalog.jsonb_build_object(
          'short', coalesce(v_payload -> 'calibrationReadiness' -> 'byModel' -> 'short', '{}'::jsonb)
            || pg_catalog.jsonb_build_object('ready', false, 'readyHorizons', 0),
          'medium', coalesce(v_payload -> 'calibrationReadiness' -> 'byModel' -> 'medium', '{}'::jsonb)
            || pg_catalog.jsonb_build_object('ready', false, 'readyHorizons', 0)
        )
      ),
    'modelObservability', pg_catalog.jsonb_build_object(
      'schemaVersion', '20.1',
      'performanceStatus', 'collecting',
      'performanceMetricsAvailable', false,
      'currentPublication', v_current_publication,
      'channels', coalesce(v_channels, '{}'::jsonb),
      'recentValidationEvents', coalesce(v_recent_validations, '[]'::jsonb),
      'runtimeByModel', coalesce(v_runtime_by_model, '{}'::jsonb),
      'validation', coalesce(v_validation, '{}'::jsonb),
      'rankChanges', coalesce(v_rank_changes, '{}'::jsonb),
      'anomalies', coalesce(v_anomalies, '{}'::jsonb)
    ),
    'summary', coalesce(v_payload -> 'summary', '{}'::jsonb)
      || pg_catalog.jsonb_build_object(
        'modelPerformanceStatus', 'collecting',
        'pendingModelOutcomes', coalesce((v_validation ->> 'pendingOutcomeCount')::integer, 0),
        'modelAnomalies', coalesce((v_anomalies ->> 'symbolCount')::integer, 0)
      )
  );
end;
$$;

revoke all on function public.twss_admin_operations_log(integer)
  from public, anon, authenticated;
grant execute on function public.twss_admin_operations_log(integer)
  to authenticated, service_role;

comment on function public.twss_admin_operations_log(integer) is
  'Intentional SECURITY DEFINER boundary for active administrators only. Adds v20.1 Champion/Challenger, immutable publication, cost, turnover, coverage, anomaly, rank-change, and collecting-only validation observability.';

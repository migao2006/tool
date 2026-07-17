-- Taiwan Stock Smart v20.1: immutable point-in-time calibration snapshots.
--
-- Calibration is derived only from the latest revision of immutable forward
-- outcome observations that was actually recorded by the requested cutoff.
-- The legacy mutable v20_calibration_buckets table remains for historical
-- compatibility, but it is not read by any v20.1 function in this migration.

create table if not exists public.v20_calibration_snapshots (
  id bigint generated always as identity primary key,
  calibration_version text not null unique
    check (calibration_version ~ '^twss-cal-sha256-[0-9a-f]{64}$'),
  model_version text not null check (pg_catalog.length(pg_catalog.btrim(model_version)) between 1 and 128),
  training_cutoff_at timestamptz not null,
  training_start_date date not null,
  training_end_date date not null,
  training_days integer not null check (training_days between 30 and 3650),
  minimum_sample_count integer not null check (minimum_sample_count >= 100),
  maximum_observation_count integer not null
    check (maximum_observation_count between 100 and 100000),
  source_observation_count integer not null
    check (source_observation_count between 100 and maximum_observation_count),
  bucket_count integer not null check (bucket_count > 0),
  calibration_method text not null check (calibration_method = 'empirical_beta_1_1'),
  positive_outcome_definition text not null
    check (positive_outcome_definition = 'net_return_gt_zero_after_costs'),
  source_version text not null check (source_version = 'immutable-outcomes-latest-revision-v1'),
  source_hash text not null check (source_hash ~ '^[0-9a-f]{64}$'),
  source_manifest jsonb not null check (pg_catalog.jsonb_typeof(source_manifest) = 'object'),
  content_hash text not null unique check (content_hash ~ '^[0-9a-f]{64}$'),
  generated_at timestamptz not null default pg_catalog.clock_timestamp(),
  check (training_start_date <= training_end_date),
  unique (id, calibration_version, model_version)
);

create table if not exists public.v20_calibration_snapshot_buckets (
  id bigint generated always as identity primary key,
  snapshot_id bigint not null,
  calibration_version text not null,
  model_key text not null check (model_key in ('short', 'medium')),
  model_version text not null,
  strategy_key text not null check (pg_catalog.length(pg_catalog.btrim(strategy_key)) between 1 and 128),
  horizon_days integer not null,
  market_regime text not null check (pg_catalog.length(pg_catalog.btrim(market_regime)) between 1 and 128),
  score_decile smallint not null check (score_decile between -1 and 9),
  minimum_sample_count integer not null check (minimum_sample_count >= 100),
  sample_count integer not null check (sample_count >= minimum_sample_count),
  wins integer not null check (wins between 0 and sample_count),
  raw_probability numeric not null check (raw_probability between 0 and 100),
  beta_prior_alpha numeric not null check (beta_prior_alpha = 1),
  beta_prior_beta numeric not null check (beta_prior_beta = 1),
  posterior_alpha numeric not null check (posterior_alpha = wins + beta_prior_alpha),
  posterior_beta numeric not null
    check (posterior_beta = (sample_count - wins) + beta_prior_beta),
  calibrated_probability numeric not null check (calibrated_probability between 0 and 100),
  average_gross_return numeric not null,
  average_net_return numeric not null,
  average_excess_return_net numeric not null,
  return_p10 numeric not null,
  return_p50 numeric not null,
  return_p90 numeric not null,
  average_mfe numeric,
  average_mae numeric,
  target_first_probability numeric check (target_first_probability between 0 and 100),
  training_start_date date not null,
  training_end_date date not null,
  first_observed_at timestamptz not null,
  last_observed_at timestamptz not null,
  source_hash text not null check (source_hash ~ '^[0-9a-f]{64}$'),
  bucket_hash text not null check (bucket_hash ~ '^[0-9a-f]{64}$'),
  recorded_at timestamptz not null default pg_catalog.clock_timestamp(),
  foreign key (snapshot_id, calibration_version, model_version)
    references public.v20_calibration_snapshots(id, calibration_version, model_version)
    on delete restrict,
  unique (
    snapshot_id,
    model_key,
    strategy_key,
    horizon_days,
    market_regime,
    score_decile
  ),
  unique (snapshot_id, bucket_hash),
  check (
    (model_key = 'short' and horizon_days in (2, 3, 5, 10))
    or (model_key = 'medium' and horizon_days in (10, 20, 40, 60))
  ),
  check (
    (strategy_key = 'all' and score_decile = -1 and minimum_sample_count >= 150)
    or (strategy_key <> 'all' and score_decile between 0 and 9)
  ),
  check (training_start_date <= training_end_date),
  check (first_observed_at <= last_observed_at)
);

create index if not exists v20_calibration_snapshots_cutoff_idx
  on public.v20_calibration_snapshots
    (model_version, training_cutoff_at desc, id desc)
  include (calibration_version, content_hash, bucket_count, minimum_sample_count);

create index if not exists v20_calibration_snapshot_buckets_lookup_idx
  on public.v20_calibration_snapshot_buckets
    (snapshot_id, model_key, horizon_days, market_regime, strategy_key, score_decile)
  include (
    sample_count,
    calibrated_probability,
    average_net_return,
    average_excess_return_net
  );

create index if not exists v20_outcome_observations_calibration_cutoff_idx
  on public.v20_outcome_observations
    (recorded_at desc, recommendation_item_id, observed_horizon_days, revision desc)
  include (observed_at, exit_date, observation_hash, net_return, excess_return_net);

alter table public.v20_calibration_snapshots enable row level security;
alter table public.v20_calibration_snapshot_buckets enable row level security;

revoke all on table
  public.v20_calibration_snapshots,
  public.v20_calibration_snapshot_buckets
from public, anon, authenticated, service_role;

grant select, insert on table
  public.v20_calibration_snapshots,
  public.v20_calibration_snapshot_buckets
to service_role;

revoke all on sequence
  public.v20_calibration_snapshots_id_seq,
  public.v20_calibration_snapshot_buckets_id_seq
from public, anon, authenticated, service_role;

grant usage, select on sequence
  public.v20_calibration_snapshots_id_seq,
  public.v20_calibration_snapshot_buckets_id_seq
to service_role;

-- The refresh RPC is SECURITY INVOKER. Grant only the cryptographic primitive
-- it needs instead of elevating the function to the table owner.
grant usage on schema extensions to service_role;
grant execute on function extensions.digest(text, text) to service_role;

drop trigger if exists v20_immutable_calibration_snapshots
  on public.v20_calibration_snapshots;
create trigger v20_immutable_calibration_snapshots
before update or delete on public.v20_calibration_snapshots
for each row execute function public.twss_v20_reject_immutable_change();

drop trigger if exists v20_immutable_calibration_snapshot_buckets
  on public.v20_calibration_snapshot_buckets;
create trigger v20_immutable_calibration_snapshot_buckets
before update or delete on public.v20_calibration_snapshot_buckets
for each row execute function public.twss_v20_reject_immutable_change();

comment on table public.v20_calibration_snapshots is
  'Append-only, content-addressed walk-forward calibration snapshots built only from immutable outcome observations available at the recorded cutoff.';
comment on table public.v20_calibration_snapshot_buckets is
  'Append-only model/strategy/horizon/regime/score-decile calibration cells; all published cells contain at least 100 point-in-time samples.';
comment on table public.v20_calibration_buckets is
  'Legacy mutable calibration table. It is not a v20.1 calibration source; v20.1 reads v20_calibration_snapshot_buckets through the service-only RPC.';

create or replace function public.twss_v20_refresh_immutable_calibration(
  p_request jsonb default '{}'::jsonb
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_cutoff_at timestamptz;
  v_cutoff_date date;
  v_model_version text;
  v_training_days integer;
  v_training_start_date date;
  v_minimum_sample_count integer;
  v_maximum_observation_count integer;
  v_bucket_payload jsonb;
  v_bucket_count integer;
  v_source_observation_count integer;
  v_source_hash text;
  v_training_end_date date;
  v_actual_training_start_date date;
  v_snapshot_hash text;
  v_calibration_version text;
  v_snapshot_id bigint;
  v_existing_id bigint;
begin
  if p_request is null or pg_catalog.jsonb_typeof(p_request) <> 'object' then
    raise exception 'v20_invalid_calibration_request' using errcode = '22023';
  end if;

  v_cutoff_at := (p_request ->> 'cutoffAt')::timestamptz;
  v_model_version := pg_catalog.btrim(coalesce(p_request ->> 'modelVersion', '20.1'));
  v_training_days := least(
    greatest(coalesce((p_request ->> 'trainingDays')::integer, 1095), 30),
    3650
  );
  v_minimum_sample_count := least(
    greatest(coalesce((p_request ->> 'minimumSampleCount')::integer, 100), 100),
    10000
  );
  v_maximum_observation_count := least(
    greatest(coalesce((p_request ->> 'maximumObservationCount')::integer, 50000), 100),
    100000
  );

  if v_cutoff_at is null
    or v_cutoff_at > pg_catalog.clock_timestamp() + interval '5 minutes'
    or v_model_version = ''
    or pg_catalog.length(v_model_version) > 128
  then
    raise exception 'v20_invalid_calibration_request' using errcode = '22023';
  end if;

  v_cutoff_date := pg_catalog.timezone('Asia/Taipei', v_cutoff_at)::date;
  v_training_start_date := v_cutoff_date - v_training_days;

  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(
      'twss-v20-calibration:' || v_model_version || ':' || v_cutoff_at::text,
      0
    )
  );

  with latest_revisions as materialized (
    select ranked.*
    from (
      select
        o.*,
        pg_catalog.row_number() over (
          partition by o.recommendation_item_id, o.observed_horizon_days
          order by o.revision desc, o.id desc
        ) as revision_order
      from public.v20_outcome_observations o
      where o.recorded_at <= v_cutoff_at
        and o.observed_at <= v_cutoff_at
        and o.exit_date <= v_cutoff_date
    ) ranked
    where ranked.revision_order = 1
  ), eligible as materialized (
    select
      o.recommendation_item_id,
      o.observed_horizon_days,
      o.revision as outcome_revision,
      o.observation_hash,
      o.observed_at,
      o.gross_return,
      o.net_return,
      o.excess_return_net,
      o.mfe,
      o.mae,
      o.target_hit_first,
      i.model_key,
      i.model_version,
      pg_catalog.left(
        coalesce(nullif(pg_catalog.btrim(i.strategy_key), ''), 'unknown'),
        128
      ) as strategy_key,
      i.horizon_days,
      i.signal_date,
      least(
        9,
        greatest(0, pg_catalog.floor(i.net_opportunity_score / 10)::integer)
      )::smallint as score_decile,
      pg_catalog.left(
        coalesce(nullif(pg_catalog.btrim(r.market_regime), ''), 'unknown'),
        128
      ) as market_regime,
      i.input_hash,
      r.content_hash as run_content_hash
    from latest_revisions o
    join public.v20_recommendation_items i
      on i.id = o.recommendation_item_id
      and i.horizon_days = o.observed_horizon_days
    join public.v20_recommendation_runs r
      on r.id = i.run_id
      and r.status = 'published'
      and r.model_version = i.model_version
      and r.data_date = i.signal_date
    where i.model_version = v_model_version
      and i.is_eligible
      and i.public_visible
      and not i.research_only
      and r.data_date >= v_training_start_date
      and r.data_date <= v_cutoff_date
      and r.data_cutoff_at <= v_cutoff_at
      and r.published_at <= v_cutoff_at
      and r.published_at < pg_catalog.timezone('Asia/Taipei', o.entry_date::timestamp)
      and not exists (
        select 1
        from public.v20_recommendation_runs later
        where later.status = 'published'
          and later.data_date = r.data_date
          and later.model_version = r.model_version
          and later.revision > r.revision
          and later.published_at < pg_catalog.timezone('Asia/Taipei', o.entry_date::timestamp)
      )
    order by o.exit_date desc, o.recommendation_item_id desc
    limit v_maximum_observation_count
  ), expanded as materialized (
    select
      e.*,
      e.strategy_key as bucket_strategy_key,
      e.score_decile as bucket_score_decile,
      v_minimum_sample_count as bucket_minimum_sample_count
    from eligible e
    where e.strategy_key <> 'all'

    union all

    select
      e.*,
      'all'::text as bucket_strategy_key,
      (-1)::smallint as bucket_score_decile,
      greatest(v_minimum_sample_count, 150) as bucket_minimum_sample_count
    from eligible e
  ), aggregated as (
    select
      x.model_key,
      x.model_version,
      x.bucket_strategy_key as strategy_key,
      x.horizon_days,
      x.market_regime,
      x.bucket_score_decile as score_decile,
      x.bucket_minimum_sample_count as minimum_sample_count,
      pg_catalog.count(*)::integer as sample_count,
      pg_catalog.count(*) filter (where x.net_return > 0)::integer as wins,
      pg_catalog.round(
        100 * pg_catalog.count(*) filter (where x.net_return > 0)::numeric
          / pg_catalog.count(*)::numeric,
        6
      ) as raw_probability,
      pg_catalog.round(
        100 * (
          pg_catalog.count(*) filter (where x.net_return > 0)::numeric + 1
        ) / (pg_catalog.count(*)::numeric + 2),
        6
      ) as calibrated_probability,
      pg_catalog.round(pg_catalog.avg(x.gross_return)::numeric, 6) as average_gross_return,
      pg_catalog.round(pg_catalog.avg(x.net_return)::numeric, 6) as average_net_return,
      pg_catalog.round(pg_catalog.avg(x.excess_return_net)::numeric, 6)
        as average_excess_return_net,
      pg_catalog.round(
        (pg_catalog.percentile_cont(0.10) within group (order by x.net_return))::numeric,
        6
      ) as return_p10,
      pg_catalog.round(
        (pg_catalog.percentile_cont(0.50) within group (order by x.net_return))::numeric,
        6
      ) as return_p50,
      pg_catalog.round(
        (pg_catalog.percentile_cont(0.90) within group (order by x.net_return))::numeric,
        6
      ) as return_p90,
      pg_catalog.round(pg_catalog.avg(x.mfe)::numeric, 6) as average_mfe,
      pg_catalog.round(pg_catalog.avg(x.mae)::numeric, 6) as average_mae,
      pg_catalog.round(
        100 * pg_catalog.avg(
          case when x.target_hit_first then 1::numeric else 0::numeric end
        ) filter (where x.target_hit_first is not null),
        6
      ) as target_first_probability,
      pg_catalog.min(x.signal_date) as training_start_date,
      pg_catalog.max(x.signal_date) as training_end_date,
      pg_catalog.min(x.observed_at) as first_observed_at,
      pg_catalog.max(x.observed_at) as last_observed_at,
      pg_catalog.encode(
        extensions.digest(
          pg_catalog.string_agg(
            x.observation_hash || ':' || x.input_hash || ':' || x.run_content_hash,
            ',' order by x.recommendation_item_id, x.outcome_revision
          ),
          'sha256'
        ),
        'hex'
      ) as source_hash
    from expanded x
    group by
      x.model_key,
      x.model_version,
      x.bucket_strategy_key,
      x.horizon_days,
      x.market_regime,
      x.bucket_score_decile,
      x.bucket_minimum_sample_count
    having pg_catalog.count(*) >= x.bucket_minimum_sample_count
  ), bucket_rows as (
    select
      a.*,
      pg_catalog.encode(
        extensions.digest(
          pg_catalog.jsonb_build_object(
            'modelKey', a.model_key,
            'modelVersion', a.model_version,
            'strategyKey', a.strategy_key,
            'horizonDays', a.horizon_days,
            'marketRegime', a.market_regime,
            'scoreDecile', a.score_decile,
            'minimumSampleCount', a.minimum_sample_count,
            'sampleCount', a.sample_count,
            'wins', a.wins,
            'rawProbability', a.raw_probability,
            'betaPriorAlpha', 1,
            'betaPriorBeta', 1,
            'calibratedProbability', a.calibrated_probability,
            'averageGrossReturn', a.average_gross_return,
            'averageNetReturn', a.average_net_return,
            'averageExcessReturnNet', a.average_excess_return_net,
            'returnP10', a.return_p10,
            'returnP50', a.return_p50,
            'returnP90', a.return_p90,
            'averageMfe', a.average_mfe,
            'averageMae', a.average_mae,
            'targetFirstProbability', a.target_first_probability,
            'trainingStartDate', a.training_start_date,
            'trainingEndDate', a.training_end_date,
            'firstObservedAt', a.first_observed_at,
            'lastObservedAt', a.last_observed_at,
            'sourceHash', a.source_hash
          )::text,
          'sha256'
        ),
        'hex'
      ) as bucket_hash
    from aggregated a
  )
  select
    coalesce(
      (
        select pg_catalog.jsonb_agg(
          pg_catalog.jsonb_build_object(
            'modelKey', b.model_key,
            'modelVersion', b.model_version,
            'strategyKey', b.strategy_key,
            'horizonDays', b.horizon_days,
            'marketRegime', b.market_regime,
            'scoreDecile', b.score_decile,
            'minimumSampleCount', b.minimum_sample_count,
            'sampleCount', b.sample_count,
            'wins', b.wins,
            'rawProbability', b.raw_probability,
            'calibratedProbability', b.calibrated_probability,
            'averageGrossReturn', b.average_gross_return,
            'averageNetReturn', b.average_net_return,
            'averageExcessReturnNet', b.average_excess_return_net,
            'returnP10', b.return_p10,
            'returnP50', b.return_p50,
            'returnP90', b.return_p90,
            'averageMfe', b.average_mfe,
            'averageMae', b.average_mae,
            'targetFirstProbability', b.target_first_probability,
            'trainingStartDate', b.training_start_date,
            'trainingEndDate', b.training_end_date,
            'firstObservedAt', b.first_observed_at,
            'lastObservedAt', b.last_observed_at,
            'sourceHash', b.source_hash,
            'bucketHash', b.bucket_hash
          ) order by
            b.model_key,
            b.horizon_days,
            b.market_regime,
            b.strategy_key,
            b.score_decile
        )
        from bucket_rows b
      ),
      '[]'::jsonb
    ),
    (select pg_catalog.count(*)::integer from eligible),
    (
      select pg_catalog.encode(
        extensions.digest(
          coalesce(
            pg_catalog.string_agg(
              e.observation_hash || ':' || e.input_hash || ':' || e.run_content_hash,
              ',' order by e.recommendation_item_id, e.outcome_revision
            ),
            'no-eligible-observations'
          ),
          'sha256'
        ),
        'hex'
      )
      from eligible e
    ),
    (select pg_catalog.min(e.signal_date) from eligible e),
    (select pg_catalog.max(e.signal_date) from eligible e)
  into
    v_bucket_payload,
    v_source_observation_count,
    v_source_hash,
    v_actual_training_start_date,
    v_training_end_date;

  v_bucket_count := pg_catalog.jsonb_array_length(v_bucket_payload);

  if v_source_observation_count < v_minimum_sample_count or v_bucket_count = 0 then
    return pg_catalog.jsonb_build_object(
      'status', 'insufficient_data',
      'source', 'immutable_outcomes_latest_revision',
      'modelVersion', v_model_version,
      'cutoffAt', v_cutoff_at,
      'sourceObservationCount', v_source_observation_count,
      'minimumSampleCount', v_minimum_sample_count,
      'bucketCount', 0,
      'calibrationVersion', null,
      'buckets', '[]'::jsonb
    );
  end if;

  v_snapshot_hash := pg_catalog.encode(
    extensions.digest(
      pg_catalog.jsonb_build_object(
        'schemaVersion', 'v20.1-immutable-calibration-v1',
        'modelVersion', v_model_version,
        'trainingCutoffAt', v_cutoff_at,
        'trainingDays', v_training_days,
        'minimumSampleCount', v_minimum_sample_count,
        'maximumObservationCount', v_maximum_observation_count,
        'sourceObservationCount', v_source_observation_count,
        'sourceHash', v_source_hash,
        'calibrationMethod', 'empirical_beta_1_1',
        'positiveOutcomeDefinition', 'net_return_gt_zero_after_costs',
        'buckets', v_bucket_payload
      )::text,
      'sha256'
    ),
    'hex'
  );
  v_calibration_version := 'twss-cal-sha256-' || v_snapshot_hash;

  select s.id into v_existing_id
  from public.v20_calibration_snapshots s
  where s.content_hash = v_snapshot_hash;

  if v_existing_id is not null then
    return pg_catalog.jsonb_build_object(
      'status', 'ready',
      'source', 'immutable_outcomes_latest_revision',
      'snapshotId', v_existing_id,
      'calibrationVersion', v_calibration_version,
      'contentHash', v_snapshot_hash,
      'cutoffAt', v_cutoff_at,
      'sourceObservationCount', v_source_observation_count,
      'minimumSampleCount', v_minimum_sample_count,
      'bucketCount', v_bucket_count,
      'idempotent', true
    );
  end if;

  insert into public.v20_calibration_snapshots (
    calibration_version,
    model_version,
    training_cutoff_at,
    training_start_date,
    training_end_date,
    training_days,
    minimum_sample_count,
    maximum_observation_count,
    source_observation_count,
    bucket_count,
    calibration_method,
    positive_outcome_definition,
    source_version,
    source_hash,
    source_manifest,
    content_hash
  ) values (
    v_calibration_version,
    v_model_version,
    v_cutoff_at,
    v_actual_training_start_date,
    v_training_end_date,
    v_training_days,
    v_minimum_sample_count,
    v_maximum_observation_count,
    v_source_observation_count,
    v_bucket_count,
    'empirical_beta_1_1',
    'net_return_gt_zero_after_costs',
    'immutable-outcomes-latest-revision-v1',
    v_source_hash,
    pg_catalog.jsonb_build_object(
      'sourceTables', pg_catalog.jsonb_build_array(
        'v20_recommendation_runs',
        'v20_recommendation_items',
        'v20_outcome_observations'
      ),
      'revisionPolicy', 'latest_revision_recorded_at_or_before_cutoff',
      'publicationPolicy', 'latest_pre_entry_run_revision',
      'cutoffAt', v_cutoff_at,
      'timezone', 'Asia/Taipei',
      'selection', 'most_recent_bounded_observations',
      'maximumObservationCount', v_maximum_observation_count,
      'probabilityMethod', pg_catalog.jsonb_build_object(
        'name', 'beta_posterior_mean',
        'alphaPrior', 1,
        'betaPrior', 1,
        'positiveOutcome', 'net_return_gt_zero_after_costs'
      ),
      'grossExcessReturnAvailable', false
    ),
    v_snapshot_hash
  )
  returning id into v_snapshot_id;

  insert into public.v20_calibration_snapshot_buckets (
    snapshot_id,
    calibration_version,
    model_key,
    model_version,
    strategy_key,
    horizon_days,
    market_regime,
    score_decile,
    minimum_sample_count,
    sample_count,
    wins,
    raw_probability,
    beta_prior_alpha,
    beta_prior_beta,
    posterior_alpha,
    posterior_beta,
    calibrated_probability,
    average_gross_return,
    average_net_return,
    average_excess_return_net,
    return_p10,
    return_p50,
    return_p90,
    average_mfe,
    average_mae,
    target_first_probability,
    training_start_date,
    training_end_date,
    first_observed_at,
    last_observed_at,
    source_hash,
    bucket_hash
  )
  select
    v_snapshot_id,
    v_calibration_version,
    bucket ->> 'modelKey',
    bucket ->> 'modelVersion',
    bucket ->> 'strategyKey',
    (bucket ->> 'horizonDays')::integer,
    bucket ->> 'marketRegime',
    (bucket ->> 'scoreDecile')::smallint,
    (bucket ->> 'minimumSampleCount')::integer,
    (bucket ->> 'sampleCount')::integer,
    (bucket ->> 'wins')::integer,
    (bucket ->> 'rawProbability')::numeric,
    1,
    1,
    (bucket ->> 'wins')::numeric + 1,
    ((bucket ->> 'sampleCount')::numeric - (bucket ->> 'wins')::numeric) + 1,
    (bucket ->> 'calibratedProbability')::numeric,
    (bucket ->> 'averageGrossReturn')::numeric,
    (bucket ->> 'averageNetReturn')::numeric,
    (bucket ->> 'averageExcessReturnNet')::numeric,
    (bucket ->> 'returnP10')::numeric,
    (bucket ->> 'returnP50')::numeric,
    (bucket ->> 'returnP90')::numeric,
    (bucket ->> 'averageMfe')::numeric,
    (bucket ->> 'averageMae')::numeric,
    (bucket ->> 'targetFirstProbability')::numeric,
    (bucket ->> 'trainingStartDate')::date,
    (bucket ->> 'trainingEndDate')::date,
    (bucket ->> 'firstObservedAt')::timestamptz,
    (bucket ->> 'lastObservedAt')::timestamptz,
    bucket ->> 'sourceHash',
    bucket ->> 'bucketHash'
  from pg_catalog.jsonb_array_elements(v_bucket_payload) bucket;

  return pg_catalog.jsonb_build_object(
    'status', 'ready',
    'source', 'immutable_outcomes_latest_revision',
    'snapshotId', v_snapshot_id,
    'calibrationVersion', v_calibration_version,
    'contentHash', v_snapshot_hash,
    'cutoffAt', v_cutoff_at,
    'sourceObservationCount', v_source_observation_count,
    'minimumSampleCount', v_minimum_sample_count,
    'bucketCount', v_bucket_count,
    'method', 'empirical_beta_1_1',
    'idempotent', false
  );
end;
$$;

revoke all on function public.twss_v20_refresh_immutable_calibration(jsonb)
  from public, anon, authenticated, service_role;
grant execute on function public.twss_v20_refresh_immutable_calibration(jsonb)
  to service_role;

comment on function public.twss_v20_refresh_immutable_calibration(jsonb) is
  'Bounded service-only refresh. Creates append-only Beta(1,1) calibration cells from the latest immutable outcome revisions available at cutoffAt; never reads legacy v20_calibration_buckets.';

create or replace function public.twss_v20_read_immutable_calibration(
  p_query jsonb default '{}'::jsonb
)
returns jsonb
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
  v_before_at timestamptz;
  v_model_version text;
  v_model_key text;
  v_strategy_key text;
  v_horizon_days integer;
  v_market_regime text;
  v_limit integer;
  v_snapshot public.v20_calibration_snapshots%rowtype;
  v_buckets jsonb;
begin
  if p_query is null or pg_catalog.jsonb_typeof(p_query) <> 'object' then
    raise exception 'v20_invalid_calibration_query' using errcode = '22023';
  end if;

  v_before_at := (p_query ->> 'beforeAt')::timestamptz;
  v_model_version := pg_catalog.btrim(coalesce(p_query ->> 'modelVersion', '20.1'));
  v_model_key := nullif(pg_catalog.btrim(coalesce(p_query ->> 'modelKey', '')), '');
  v_strategy_key := nullif(pg_catalog.btrim(coalesce(p_query ->> 'strategyKey', '')), '');
  v_horizon_days := (p_query ->> 'horizonDays')::integer;
  v_market_regime := nullif(pg_catalog.btrim(coalesce(p_query ->> 'marketRegime', '')), '');
  v_limit := least(greatest(coalesce((p_query ->> 'limit')::integer, 2000), 1), 5000);

  if v_before_at is null
    or v_model_version = ''
    or pg_catalog.length(v_model_version) > 128
    or (v_model_key is not null and v_model_key not in ('short', 'medium'))
    or (
      v_horizon_days is not null
      and not (
        (v_model_key = 'short' and v_horizon_days in (2, 3, 5, 10))
        or (v_model_key = 'medium' and v_horizon_days in (10, 20, 40, 60))
        or (v_model_key is null and v_horizon_days in (2, 3, 5, 10, 20, 40, 60))
      )
    )
  then
    raise exception 'v20_invalid_calibration_query' using errcode = '22023';
  end if;

  select s.* into v_snapshot
  from public.v20_calibration_snapshots s
  where s.model_version = v_model_version
    and s.training_cutoff_at <= v_before_at
  order by s.training_cutoff_at desc, s.id desc
  limit 1;

  if not found then
    return pg_catalog.jsonb_build_object(
      'status', 'not_ready',
      'source', 'immutable_calibration_snapshots',
      'modelVersion', v_model_version,
      'beforeAt', v_before_at,
      'calibrationVersion', null,
      'buckets', '[]'::jsonb
    );
  end if;

  select coalesce(
    pg_catalog.jsonb_agg(
      pg_catalog.jsonb_build_object(
        'calibration_version', b.calibration_version,
        'calibration_cutoff_at', v_snapshot.training_cutoff_at,
        'calibration_method', v_snapshot.calibration_method,
        'prediction_basis', 'walk-forward-calibration',
        'model_key', b.model_key,
        'model_version', b.model_version,
        'strategy_key', b.strategy_key,
        'horizon_days', b.horizon_days,
        'market_regime', b.market_regime,
        'score_decile', b.score_decile,
        'minimum_sample_count', b.minimum_sample_count,
        'sample_count', b.sample_count,
        'wins', b.wins,
        'raw_probability', b.raw_probability,
        'calibrated_probability', b.calibrated_probability,
        'beta_prior_alpha', b.beta_prior_alpha,
        'beta_prior_beta', b.beta_prior_beta,
        'average_gross_return', b.average_gross_return,
        'average_net_return', b.average_net_return,
        'average_excess_return_gross', null,
        'average_excess_return_net', b.average_excess_return_net,
        'return_p10', b.return_p10,
        'return_p50', b.return_p50,
        'return_p90', b.return_p90,
        'average_mfe', b.average_mfe,
        'average_mae', b.average_mae,
        'target_first_probability', b.target_first_probability,
        'training_start', b.training_start_date,
        'training_end', b.training_end_date,
        'source_hash', b.source_hash,
        'bucket_hash', b.bucket_hash
      ) order by b.model_key, b.horizon_days, b.market_regime, b.strategy_key, b.score_decile
    ),
    '[]'::jsonb
  ) into v_buckets
  from (
    select source.*
    from public.v20_calibration_snapshot_buckets source
    where source.snapshot_id = v_snapshot.id
      and (v_model_key is null or source.model_key = v_model_key)
      and (v_strategy_key is null or source.strategy_key = v_strategy_key)
      and (v_horizon_days is null or source.horizon_days = v_horizon_days)
      and (v_market_regime is null or source.market_regime = v_market_regime)
    order by source.model_key, source.horizon_days, source.market_regime,
      source.strategy_key, source.score_decile
    limit v_limit
  ) b;

  return pg_catalog.jsonb_build_object(
    'status', 'ready',
    'source', 'immutable_calibration_snapshots',
    'snapshotId', v_snapshot.id,
    'calibrationVersion', v_snapshot.calibration_version,
    'contentHash', v_snapshot.content_hash,
    'modelVersion', v_snapshot.model_version,
    'trainingCutoffAt', v_snapshot.training_cutoff_at,
    'trainingStartDate', v_snapshot.training_start_date,
    'trainingEndDate', v_snapshot.training_end_date,
    'minimumSampleCount', v_snapshot.minimum_sample_count,
    'sourceObservationCount', v_snapshot.source_observation_count,
    'bucketCount', pg_catalog.jsonb_array_length(v_buckets),
    'totalBucketCount', v_snapshot.bucket_count,
    'method', v_snapshot.calibration_method,
    'positiveOutcomeDefinition', v_snapshot.positive_outcome_definition,
    'buckets', v_buckets
  );
end;
$$;

revoke all on function public.twss_v20_read_immutable_calibration(jsonb)
  from public, anon, authenticated, service_role;
grant execute on function public.twss_v20_read_immutable_calibration(jsonb)
  to service_role;

comment on function public.twss_v20_read_immutable_calibration(jsonb) is
  'Service-only point-in-time resolver. Returns the newest immutable calibration snapshot whose training cutoff is not later than beforeAt, plus model-compatible bucket rows and calibrationVersion.';

create or replace function public.twss_v20_validate_run_calibration_reference()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
  if new.calibration_version is null then
    return new;
  end if;

  if not exists (
    select 1
    from public.v20_calibration_snapshots s
    where s.calibration_version = new.calibration_version
      and s.model_version = new.model_version
      and s.training_cutoff_at <= new.data_cutoff_at
  ) then
    raise exception 'v20_invalid_or_future_calibration_reference' using errcode = '23503';
  end if;

  return new;
end;
$$;

drop trigger if exists v20_validate_run_calibration_reference
  on public.v20_recommendation_runs;
create trigger v20_validate_run_calibration_reference
before insert on public.v20_recommendation_runs
for each row execute function public.twss_v20_validate_run_calibration_reference();

revoke all on function public.twss_v20_validate_run_calibration_reference()
  from public, anon, authenticated, service_role;

do $$
begin
  if not exists (
    select 1
    from pg_catalog.pg_constraint c
    where c.conrelid = 'public.v20_recommendation_runs'::regclass
      and c.conname = 'v20_recommendation_runs_calibration_version_fkey'
  ) then
    alter table public.v20_recommendation_runs
      add constraint v20_recommendation_runs_calibration_version_fkey
      foreign key (calibration_version)
      references public.v20_calibration_snapshots(calibration_version)
      on delete restrict
      not valid;
  end if;
end;
$$;

-- Bind every new immutable publication to the exact short and medium Champion
-- releases that were active while the publication transaction was running.
-- Historical rows remain readable: the new foreign keys are intentionally
-- nullable, while the insert trigger requires them for every future row.

alter table public.v20_recommendation_runs
  add column if not exists short_release_id bigint
    references public.v20_model_releases(id) on delete restrict,
  add column if not exists medium_release_id bigint
    references public.v20_model_releases(id) on delete restrict;

create index if not exists v20_recommendation_runs_short_release_idx
  on public.v20_recommendation_runs (short_release_id)
  where short_release_id is not null;

create index if not exists v20_recommendation_runs_medium_release_idx
  on public.v20_recommendation_runs (medium_release_id)
  where medium_release_id is not null;

comment on column public.v20_recommendation_runs.short_release_id is
  'Exact validated short Champion release atomically bound to this immutable publication. Null only for historical rows created before the binding migration.';
comment on column public.v20_recommendation_runs.medium_release_id is
  'Exact validated medium Champion release atomically bound to this immutable publication. Null only for historical rows created before the binding migration.';

create or replace function public.twss_v20_bind_run_to_champion_releases()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_short_binding jsonb := new.model_manifest #> '{short,championRelease}';
  v_medium_binding jsonb := new.model_manifest #> '{medium,championRelease}';
  v_short_release_id bigint;
  v_medium_release_id bigint;
  v_short_release public.v20_model_releases%rowtype;
  v_medium_release public.v20_model_releases%rowtype;
  v_code_hash text := pg_catalog.lower(pg_catalog.btrim(coalesce(new.code_hash, '')));
begin
  if new.model_manifest ->> 'publicationBindingVersion'
      is distinct from 'champion-release-v1'
    or pg_catalog.jsonb_typeof(v_short_binding) is distinct from 'object'
    or pg_catalog.jsonb_typeof(v_medium_binding) is distinct from 'object'
  then
    raise exception 'v20_champion_release_binding_required' using errcode = '22023';
  end if;

  begin
    v_short_release_id := nullif(v_short_binding ->> 'releaseId', '')::bigint;
    v_medium_release_id := nullif(v_medium_binding ->> 'releaseId', '')::bigint;
  exception
    when invalid_text_representation or numeric_value_out_of_range then
      raise exception 'v20_invalid_champion_release_binding' using errcode = '22023';
  end;

  if v_short_release_id is null
    or v_medium_release_id is null
    or v_short_binding ->> 'modelKey' is distinct from 'short'
    or v_medium_binding ->> 'modelKey' is distinct from 'medium'
    or v_short_binding ->> 'channel' is distinct from 'champion'
    or v_medium_binding ->> 'channel' is distinct from 'champion'
  then
    raise exception 'v20_invalid_champion_release_binding' using errcode = '22023';
  end if;

  select r.*
  into v_short_release
  from public.v20_model_releases r
  join public.v20_model_channel_heads h
    on h.release_id = r.id
   and h.model_key = 'short'
   and h.channel = 'champion'
  where r.id = v_short_release_id
  for share of r;

  if not found then
    raise exception 'v20_short_champion_release_changed' using errcode = '40001';
  end if;

  select r.*
  into v_medium_release
  from public.v20_model_releases r
  join public.v20_model_channel_heads h
    on h.release_id = r.id
   and h.model_key = 'medium'
   and h.channel = 'champion'
  where r.id = v_medium_release_id
  for share of r;

  if not found then
    raise exception 'v20_medium_champion_release_changed' using errcode = '40001';
  end if;

  if v_short_release.validation_status <> 'passed'
    or v_medium_release.validation_status <> 'passed'
  then
    raise exception 'v20_publication_requires_passed_champions' using errcode = '22023';
  end if;

  if v_code_hash !~ '^[0-9a-f]{64}$'
    or pg_catalog.lower(v_short_release.artifact_hash) <> v_code_hash
    or pg_catalog.lower(v_medium_release.artifact_hash) <> v_code_hash
    or pg_catalog.lower(v_short_binding ->> 'artifactHash') is distinct from v_code_hash
    or pg_catalog.lower(v_medium_binding ->> 'artifactHash') is distinct from v_code_hash
  then
    raise exception 'v20_champion_artifact_hash_mismatch' using errcode = '22023';
  end if;

  if v_short_release.model_version <> new.model_version
    or v_medium_release.model_version <> new.model_version
    or v_short_release.feature_version <> new.feature_version
    or v_medium_release.feature_version <> new.feature_version
    or v_short_release.cost_model_version <> new.cost_model_version
    or v_medium_release.cost_model_version <> new.cost_model_version
    or v_short_release.calibration_version is distinct from new.calibration_version
    or v_medium_release.calibration_version is distinct from new.calibration_version
    or v_short_binding ->> 'modelVersion' is distinct from new.model_version
    or v_medium_binding ->> 'modelVersion' is distinct from new.model_version
    or v_short_binding ->> 'featureVersion' is distinct from new.feature_version
    or v_medium_binding ->> 'featureVersion' is distinct from new.feature_version
    or v_short_binding ->> 'costModelVersion' is distinct from new.cost_model_version
    or v_medium_binding ->> 'costModelVersion' is distinct from new.cost_model_version
    or nullif(v_short_binding ->> 'calibrationVersion', '')
      is distinct from new.calibration_version
    or nullif(v_medium_binding ->> 'calibrationVersion', '')
      is distinct from new.calibration_version
  then
    raise exception 'v20_champion_release_manifest_mismatch' using errcode = '22023';
  end if;

  new.code_hash := v_code_hash;
  new.short_release_id := v_short_release_id;
  new.medium_release_id := v_medium_release_id;
  return new;
end;
$$;

revoke all on function public.twss_v20_bind_run_to_champion_releases()
  from public, anon, authenticated, service_role;

drop trigger if exists v20_bind_run_to_champion_releases
  on public.v20_recommendation_runs;
create trigger v20_bind_run_to_champion_releases
before insert on public.v20_recommendation_runs
for each row execute function public.twss_v20_bind_run_to_champion_releases();

-- Preserve the original complete-cycle publisher as an owner-only
-- implementation detail. The public RPC below becomes the sole service entry.
do $$
begin
  if pg_catalog.to_regprocedure(
    'public.twss_v20_publish_recommendation_run_champion_base(jsonb)'
  ) is null then
    alter function public.twss_v20_publish_recommendation_run(jsonb)
      rename to twss_v20_publish_recommendation_run_champion_base;
  end if;
end
$$;

revoke all on function public.twss_v20_publish_recommendation_run_champion_base(jsonb)
  from public, anon, authenticated, service_role;

create or replace function public.twss_v20_publish_recommendation_run(p_request jsonb)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_model_version text;
  v_feature_version text;
  v_cost_model_version text;
  v_calibration_version text;
  v_code_hash text;
  v_model_manifest jsonb;
  v_short_release public.v20_model_releases%rowtype;
  v_medium_release public.v20_model_releases%rowtype;
  v_short_binding jsonb;
  v_medium_binding jsonb;
  v_enriched_request jsonb;
  v_result jsonb;
begin
  if p_request is null or pg_catalog.jsonb_typeof(p_request) <> 'object' then
    raise exception 'v20_invalid_publication_request' using errcode = '22023';
  end if;

  v_model_version := pg_catalog.btrim(coalesce(p_request ->> 'modelVersion', ''));
  v_feature_version := pg_catalog.btrim(coalesce(p_request ->> 'featureVersion', ''));
  v_cost_model_version := pg_catalog.btrim(coalesce(p_request ->> 'costModelVersion', ''));
  v_calibration_version := nullif(
    pg_catalog.btrim(coalesce(p_request ->> 'calibrationVersion', '')),
    ''
  );
  v_code_hash := pg_catalog.lower(pg_catalog.btrim(coalesce(p_request ->> 'codeHash', '')));
  v_model_manifest := coalesce(p_request -> 'modelManifest', '{}'::jsonb);

  if v_model_version = ''
    or v_feature_version = ''
    or v_cost_model_version = ''
    or v_code_hash !~ '^[0-9a-f]{64}$'
    or pg_catalog.jsonb_typeof(v_model_manifest) is distinct from 'object'
    or pg_catalog.jsonb_typeof(v_model_manifest -> 'short') is distinct from 'object'
    or pg_catalog.jsonb_typeof(v_model_manifest -> 'medium') is distinct from 'object'
  then
    raise exception 'v20_invalid_champion_publication_metadata' using errcode = '22023';
  end if;

  -- The channel mutators use these same keys. Always acquire them in this
  -- short-then-medium order so neither Champion can change before commit.
  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('twss-v20-model-channel:short', 0)
  );
  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('twss-v20-model-channel:medium', 0)
  );

  select r.*
  into v_short_release
  from public.v20_model_channel_heads h
  join public.v20_model_releases r on r.id = h.release_id
  where h.model_key = 'short'
    and h.channel = 'champion'
  for share of r;

  if not found then
    raise exception 'v20_short_champion_required' using errcode = '22023';
  end if;

  select r.*
  into v_medium_release
  from public.v20_model_channel_heads h
  join public.v20_model_releases r on r.id = h.release_id
  where h.model_key = 'medium'
    and h.channel = 'champion'
  for share of r;

  if not found then
    raise exception 'v20_medium_champion_required' using errcode = '22023';
  end if;

  if v_short_release.validation_status <> 'passed'
    or v_medium_release.validation_status <> 'passed'
  then
    raise exception 'v20_publication_requires_passed_champions' using errcode = '22023';
  end if;

  if v_short_release.model_version <> v_model_version
    or v_medium_release.model_version <> v_model_version
  then
    raise exception 'v20_champion_model_version_mismatch' using errcode = '22023';
  end if;

  if v_short_release.feature_version <> v_feature_version
    or v_medium_release.feature_version <> v_feature_version
  then
    raise exception 'v20_champion_feature_version_mismatch' using errcode = '22023';
  end if;

  if v_short_release.cost_model_version <> v_cost_model_version
    or v_medium_release.cost_model_version <> v_cost_model_version
  then
    raise exception 'v20_champion_cost_model_version_mismatch' using errcode = '22023';
  end if;

  if v_short_release.calibration_version is distinct from v_calibration_version
    or v_medium_release.calibration_version is distinct from v_calibration_version
  then
    raise exception 'v20_champion_calibration_version_mismatch' using errcode = '22023';
  end if;

  if pg_catalog.lower(v_short_release.artifact_hash) <> v_code_hash
    or pg_catalog.lower(v_medium_release.artifact_hash) <> v_code_hash
    or pg_catalog.lower(v_short_release.artifact_hash)
      <> pg_catalog.lower(v_medium_release.artifact_hash)
  then
    raise exception 'v20_champion_artifact_hash_mismatch' using errcode = '22023';
  end if;

  v_short_binding := pg_catalog.jsonb_build_object(
    'modelKey', 'short',
    'channel', 'champion',
    'releaseId', v_short_release.id,
    'artifactHash', v_code_hash,
    'modelVersion', v_short_release.model_version,
    'featureVersion', v_short_release.feature_version,
    'costModelVersion', v_short_release.cost_model_version,
    'calibrationVersion', v_short_release.calibration_version
  );
  v_medium_binding := pg_catalog.jsonb_build_object(
    'modelKey', 'medium',
    'channel', 'champion',
    'releaseId', v_medium_release.id,
    'artifactHash', v_code_hash,
    'modelVersion', v_medium_release.model_version,
    'featureVersion', v_medium_release.feature_version,
    'costModelVersion', v_medium_release.cost_model_version,
    'calibrationVersion', v_medium_release.calibration_version
  );

  -- Overwrite caller-supplied release bindings. Challenger IDs can never be
  -- selected through this RPC, even if they are injected into modelManifest.
  v_model_manifest := pg_catalog.jsonb_set(
    v_model_manifest,
    '{short,championRelease}',
    v_short_binding,
    true
  );
  v_model_manifest := pg_catalog.jsonb_set(
    v_model_manifest,
    '{medium,championRelease}',
    v_medium_binding,
    true
  );
  v_model_manifest := v_model_manifest || pg_catalog.jsonb_build_object(
    'publicationBindingVersion', 'champion-release-v1'
  );

  v_enriched_request := pg_catalog.jsonb_set(
    p_request,
    '{modelManifest}',
    v_model_manifest,
    true
  );
  v_enriched_request := pg_catalog.jsonb_set(
    v_enriched_request,
    '{codeHash}',
    pg_catalog.to_jsonb(v_code_hash),
    true
  );

  v_result := public.twss_v20_publish_recommendation_run_champion_base(
    v_enriched_request
  );

  return coalesce(v_result, '{}'::jsonb) || pg_catalog.jsonb_build_object(
    'shortReleaseId', v_short_release.id,
    'mediumReleaseId', v_medium_release.id,
    'championArtifactHash', v_code_hash,
    'publicationBindingVersion', 'champion-release-v1'
  );
end;
$$;

revoke all on function public.twss_v20_publish_recommendation_run(jsonb)
  from public, anon, authenticated;
grant execute on function public.twss_v20_publish_recommendation_run(jsonb)
  to service_role;

comment on function public.twss_v20_publish_recommendation_run_champion_base(jsonb) is
  'Owner-only complete-cycle publisher implementation. Call the Champion-binding wrapper instead.';
comment on function public.twss_v20_publish_recommendation_run(jsonb) is
  'Service-only atomic publisher. It locks and validates the short and medium Champion releases, binds their IDs and shared artifact hash into the immutable model manifest, then publishes.';

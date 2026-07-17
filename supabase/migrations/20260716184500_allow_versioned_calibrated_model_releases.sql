-- A calibration snapshot is part of a model release's immutable identity.
-- The same code artifact may therefore be registered once without calibration
-- and again for each independently versioned calibration snapshot.

do $$
declare
  v_constraint_name name;
begin
  for v_constraint_name in
    select c.conname
    from pg_catalog.pg_constraint c
    where c.conrelid = 'public.v20_model_releases'::regclass
      and c.contype = 'u'
      and (
        select pg_catalog.array_agg(a.attname::text order by k.ordinality)
        from pg_catalog.unnest(c.conkey) with ordinality as k(attnum, ordinality)
        join pg_catalog.pg_attribute a
          on a.attrelid = c.conrelid
         and a.attnum = k.attnum
      ) = array['model_key', 'model_version', 'artifact_hash']::text[]
  loop
    execute pg_catalog.format(
      'alter table public.v20_model_releases drop constraint %I',
      v_constraint_name
    );
  end loop;
end
$$;

create unique index if not exists v20_model_releases_versioned_identity_uq
  on public.v20_model_releases (
    model_key,
    model_version,
    artifact_hash,
    (coalesce(calibration_version, ''))
  );

comment on index public.v20_model_releases_versioned_identity_uq is
  'Immutable model release identity, including the optional calibration snapshot version.';

create or replace function public.twss_v20_register_model_release(p_release jsonb)
returns bigint
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_id bigint;
  v_model_key text;
  v_model_version text;
  v_artifact_hash text;
  v_feature_version text;
  v_cost_model_version text;
  v_calibration_version text;
  v_validation_status text;
begin
  if p_release is null or pg_catalog.jsonb_typeof(p_release) <> 'object' then
    raise exception 'v20_invalid_model_release' using errcode = '22023';
  end if;

  v_model_key := pg_catalog.btrim(coalesce(p_release ->> 'modelKey', ''));
  v_model_version := pg_catalog.btrim(coalesce(p_release ->> 'modelVersion', ''));
  v_artifact_hash := pg_catalog.lower(
    pg_catalog.btrim(coalesce(p_release ->> 'artifactHash', ''))
  );
  v_feature_version := pg_catalog.btrim(coalesce(p_release ->> 'featureVersion', ''));
  v_cost_model_version := pg_catalog.btrim(
    coalesce(p_release ->> 'costModelVersion', '')
  );
  v_calibration_version := nullif(
    pg_catalog.btrim(coalesce(p_release ->> 'calibrationVersion', '')),
    ''
  );
  v_validation_status := pg_catalog.btrim(
    coalesce(p_release ->> 'validationStatus', 'shadow')
  );

  if v_model_key not in ('short', 'medium')
    or v_model_version = ''
    or v_artifact_hash !~ '^[0-9a-f]{64}$'
    or v_feature_version = ''
    or v_cost_model_version = ''
    or v_validation_status not in ('shadow', 'passed', 'failed')
    or pg_catalog.jsonb_typeof(coalesce(p_release -> 'configuration', '{}'::jsonb)) <> 'object'
    or pg_catalog.jsonb_typeof(coalesce(p_release -> 'validationMetrics', '{}'::jsonb)) <> 'object'
  then
    raise exception 'v20_invalid_model_release' using errcode = '22023';
  end if;

  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(
      'twss-v20-model-release:'
        || v_model_key
        || ':'
        || v_model_version
        || ':'
        || v_artifact_hash
        || ':calibration:'
        || coalesce(v_calibration_version, '<none>'),
      0
    )
  );

  select r.id
  into v_id
  from public.v20_model_releases r
  where r.model_key = v_model_key
    and r.model_version = v_model_version
    and r.artifact_hash = v_artifact_hash
    and r.calibration_version is not distinct from v_calibration_version;

  if v_id is not null then
    return v_id;
  end if;

  insert into public.v20_model_releases (
    model_key,
    model_version,
    artifact_hash,
    feature_version,
    cost_model_version,
    calibration_version,
    validation_status,
    configuration,
    validation_metrics,
    registered_by
  )
  select
    v_model_key,
    v_model_version,
    v_artifact_hash,
    v_feature_version,
    v_cost_model_version,
    v_calibration_version,
    v_validation_status,
    coalesce(p_release -> 'configuration', '{}'::jsonb),
    coalesce(p_release -> 'validationMetrics', '{}'::jsonb),
    coalesce(
      nullif(pg_catalog.btrim(coalesce(p_release ->> 'registeredBy', '')), ''),
      'service_role'
    )
  where not exists (
    select 1
    from public.v20_model_releases r
    where r.model_key = v_model_key
      and r.model_version = v_model_version
      and r.artifact_hash = v_artifact_hash
      and r.calibration_version is not distinct from v_calibration_version
  )
  on conflict do nothing
  returning id into v_id;

  if v_id is null then
    select r.id
    into v_id
    from public.v20_model_releases r
    where r.model_key = v_model_key
      and r.model_version = v_model_version
      and r.artifact_hash = v_artifact_hash
      and r.calibration_version is not distinct from v_calibration_version;

    if v_id is not null then
      return v_id;
    end if;
  end if;

  if v_id is null then
    raise exception 'v20_model_release_registration_failed' using errcode = '40001';
  end if;

  insert into public.v20_model_validation_events (
    release_id,
    validation_status,
    validation_metrics,
    window_start,
    window_end,
    notes,
    recorded_by
  ) values (
    v_id,
    v_validation_status,
    coalesce(p_release -> 'validationMetrics', '{}'::jsonb),
    nullif(p_release ->> 'validationWindowStart', '')::date,
    nullif(p_release ->> 'validationWindowEnd', '')::date,
    nullif(
      pg_catalog.left(
        pg_catalog.btrim(coalesce(p_release ->> 'validationNotes', '')),
        2000
      ),
      ''
    ),
    coalesce(
      nullif(pg_catalog.btrim(coalesce(p_release ->> 'registeredBy', '')), ''),
      'service_role'
    )
  );

  return v_id;
end;
$$;

revoke all on function public.twss_v20_register_model_release(jsonb)
  from public, anon, authenticated, service_role;
grant execute on function public.twss_v20_register_model_release(jsonb)
  to service_role;

comment on function public.twss_v20_register_model_release(jsonb) is
  'Service-only append-only registration. Identity includes model, exact 64-hex artifact and optional calibration version; repeated registration never mutates an existing release.';

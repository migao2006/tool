begin;

do $validation$
declare
  v_config text[];
begin
  select procedure.proconfig
    into v_config
  from pg_proc as procedure
  join pg_namespace as namespace
    on namespace.oid = procedure.pronamespace
  where procedure.oid = to_regprocedure(
    'market_data.publish_research_prediction_snapshot_twse_v1(jsonb,jsonb)'
  )
    and namespace.nspname = 'market_data';

  if not found then
    raise exception 'legacy prediction publisher backup is missing';
  end if;

  if not ('plpgsql_check.mode=disabled' = any(coalesce(v_config, '{}'::text[]))) then
    raise exception 'legacy prediction publisher lint exclusion is missing';
  end if;

  if has_function_privilege(
    'service_role',
    'market_data.publish_research_prediction_snapshot_twse_v1(jsonb,jsonb)',
    'EXECUTE'
  ) or has_function_privilege(
    'anon',
    'market_data.publish_research_prediction_snapshot_twse_v1(jsonb,jsonb)',
    'EXECUTE'
  ) or has_function_privilege(
    'authenticated',
    'market_data.publish_research_prediction_snapshot_twse_v1(jsonb,jsonb)',
    'EXECUTE'
  ) then
    raise exception 'legacy prediction publisher backup is callable';
  end if;

  if not exists (
    select 1
    from pg_constraint as constraint_record
    where constraint_record.conrelid =
      'market_data.prediction_runs'::regclass
      and constraint_record.conname = 'prediction_runs_market_identity_key'
      and constraint_record.contype = 'u'
      and pg_get_constraintdef(constraint_record.oid) =
        'UNIQUE (market_scope, decision_at, horizon, model_bundle_version)'
  ) then
    raise exception 'market-scoped prediction identity changed unexpectedly';
  end if;
end
$validation$;

rollback;

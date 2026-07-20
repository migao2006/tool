begin;

set local lock_timeout = '5s';
set local statement_timeout = '60s';

-- This function is an exact rollback copy of the pre-market-scope publisher.
-- Its legacy ON CONFLICT target is intentionally valid only after the
-- market-scope migration is rolled back. Keep the body unchanged and exclude
-- only this unreachable backup from plpgsql_check on the current schema.
do $guard$
begin
  if to_regprocedure(
    'market_data.publish_research_prediction_snapshot_twse_v1(jsonb,jsonb)'
  ) is null then
    raise exception using
      errcode = '42883',
      message = 'LEGACY_PREDICTION_PUBLISHER_BACKUP_IS_MISSING';
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
    raise exception using
      errcode = '42501',
      message = 'LEGACY_PREDICTION_PUBLISHER_BACKUP_MUST_REMAIN_UNCALLABLE';
  end if;
end
$guard$;

alter function
market_data.publish_research_prediction_snapshot_twse_v1(jsonb, jsonb)
set "plpgsql_check.mode" to 'disabled';

commit;

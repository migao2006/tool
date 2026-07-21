begin;

set local lock_timeout = '5s';
set local statement_timeout = '60s';

do $validation$
declare
  v_key text := repeat('a', 64);
  v_first record;
  v_second record;
  v_third record;
  v_security_definer boolean;
begin
  delete from market_data.prediction_snapshot_rate_limits
  where rate_limit_key_sha256 = v_key;

  select * into strict v_first
  from market_data.consume_prediction_snapshot_rate_limit(v_key, 60, 2);
  select * into strict v_second
  from market_data.consume_prediction_snapshot_rate_limit(v_key, 60, 2);
  select * into strict v_third
  from market_data.consume_prediction_snapshot_rate_limit(v_key, 60, 2);

  if v_first.allowed is distinct from true
     or v_first.remaining is distinct from 1
     or v_first.retry_after_seconds is distinct from 0 then
    raise exception 'FIRST_RATE_LIMIT_DECISION_INVALID';
  end if;
  if v_second.allowed is distinct from true
     or v_second.remaining is distinct from 0
     or v_second.retry_after_seconds is distinct from 0 then
    raise exception 'SECOND_RATE_LIMIT_DECISION_INVALID';
  end if;
  if v_third.allowed is distinct from false
     or v_third.remaining is distinct from 0
     or v_third.retry_after_seconds < 1 then
    raise exception 'THIRD_RATE_LIMIT_DECISION_INVALID';
  end if;

  if has_function_privilege(
    'anon',
    'market_data.consume_prediction_snapshot_rate_limit(text,integer,integer)',
    'EXECUTE'
  ) or has_function_privilege(
    'authenticated',
    'market_data.consume_prediction_snapshot_rate_limit(text,integer,integer)',
    'EXECUTE'
  ) then
    raise exception 'RATE_LIMIT_FUNCTION_EXPOSED_TO_BROWSER_ROLES';
  end if;
  if not has_function_privilege(
    'service_role',
    'market_data.consume_prediction_snapshot_rate_limit(text,integer,integer)',
    'EXECUTE'
  ) then
    raise exception 'RATE_LIMIT_FUNCTION_MISSING_SERVICE_ROLE_GRANT';
  end if;

  select procedure.prosecdef
  into strict v_security_definer
  from pg_proc as procedure
  join pg_namespace as namespace
    on namespace.oid = procedure.pronamespace
  where namespace.nspname = 'market_data'
    and procedure.proname = 'consume_prediction_snapshot_rate_limit'
    and pg_get_function_identity_arguments(procedure.oid) =
      'p_key_sha256 text, p_window_seconds integer, p_max_requests integer';

  if v_security_definer then
    raise exception 'RATE_LIMIT_FUNCTION_MUST_BE_SECURITY_INVOKER';
  end if;
end;
$validation$;

rollback;

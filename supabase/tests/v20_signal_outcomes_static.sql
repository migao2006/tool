-- Run after applying 20260716024526_add_v20_signal_outcomes_calibration.sql.
-- This is catalog-only: it does not insert, update, or delete application data.

begin;

do $test$
declare
  v_rls boolean;
  v_policy_count integer;
  v_is_definer boolean;
  v_proconfig text[];
begin
  if pg_catalog.to_regclass('public.v20_signal_outcomes') is null then
    raise exception 'missing public.v20_signal_outcomes';
  end if;

  select c.relrowsecurity
  into v_rls
  from pg_catalog.pg_class c
  where c.oid = 'public.v20_signal_outcomes'::pg_catalog.regclass;

  if not coalesce(v_rls, false) then
    raise exception 'v20_signal_outcomes RLS is disabled';
  end if;

  select pg_catalog.count(*)::integer
  into v_policy_count
  from pg_catalog.pg_policies
  where schemaname = 'public' and tablename = 'v20_signal_outcomes';

  if v_policy_count <> 0 then
    raise exception 'v20_signal_outcomes must remain server-only (found % policies)', v_policy_count;
  end if;

  if pg_catalog.has_table_privilege('anon', 'public.v20_signal_outcomes', 'SELECT')
    or pg_catalog.has_table_privilege('authenticated', 'public.v20_signal_outcomes', 'SELECT')
  then
    raise exception 'public API roles can read server-only v20_signal_outcomes';
  end if;

  if not pg_catalog.has_table_privilege('service_role', 'public.v20_signal_outcomes', 'SELECT')
    or not pg_catalog.has_table_privilege('service_role', 'public.v20_signal_outcomes', 'INSERT')
    or not pg_catalog.has_table_privilege('service_role', 'public.v20_signal_outcomes', 'UPDATE')
  then
    raise exception 'service_role is missing required v20_signal_outcomes DML privileges';
  end if;

  if not exists (
    select 1
    from pg_catalog.pg_constraint c
    where c.conrelid = 'public.v20_signal_outcomes'::pg_catalog.regclass
      and c.contype = 'p'
  ) then
    raise exception 'v20_signal_outcomes primary key missing';
  end if;

  if not exists (
    select 1
    from pg_catalog.pg_constraint c
    where c.conrelid = 'public.v20_signal_outcomes'::pg_catalog.regclass
      and c.confrelid = 'public.v20_model_signals'::pg_catalog.regclass
      and c.contype = 'f'
  ) then
    raise exception 'v20_signal_outcomes signal foreign key missing';
  end if;

  if not exists (
    select 1
    from pg_catalog.pg_indexes
    where schemaname = 'public'
      and indexname = 'v20_signal_outcomes_calibration_idx'
  ) then
    raise exception 'v20_signal_outcomes calibration index missing';
  end if;

  if not exists (
    select 1
    from pg_catalog.pg_trigger t
    where t.tgrelid = 'public.v20_signal_outcomes'::pg_catalog.regclass
      and t.tgname = 'v20_signal_outcomes_set_updated_at'
      and not t.tgisinternal
  ) then
    raise exception 'v20_signal_outcomes updated_at trigger missing';
  end if;

  select p.prosecdef, p.proconfig
  into v_is_definer, v_proconfig
  from pg_catalog.pg_proc p
  where p.oid = pg_catalog.to_regprocedure(
    'public.twss_v20_refresh_signal_calibration(date,text)'
  );

  if v_is_definer is distinct from false then
    raise exception 'calibration RPC must be SECURITY INVOKER';
  end if;

  if not exists (
    select 1
    from pg_catalog.unnest(v_proconfig) setting
    where setting like 'search_path=%'
  ) then
    raise exception 'calibration RPC must pin an empty search_path';
  end if;

  select p.prosecdef, p.proconfig
  into v_is_definer, v_proconfig
  from pg_catalog.pg_proc p
  where p.oid = pg_catalog.to_regprocedure(
    'public.twss_v20_evaluate_signal_outcomes(date,text,text,integer,numeric,numeric,numeric,numeric,numeric,numeric)'
  );

  if v_is_definer is distinct from false then
    raise exception 'outcome RPC must be SECURITY INVOKER';
  end if;

  if not exists (
    select 1
    from pg_catalog.unnest(v_proconfig) setting
    where setting like 'search_path=%'
  ) then
    raise exception 'outcome RPC must pin an empty search_path';
  end if;

  if pg_catalog.has_function_privilege(
      'anon',
      'public.twss_v20_evaluate_signal_outcomes(date,text,text,integer,numeric,numeric,numeric,numeric,numeric,numeric)',
      'EXECUTE'
    )
    or pg_catalog.has_function_privilege(
      'authenticated',
      'public.twss_v20_evaluate_signal_outcomes(date,text,text,integer,numeric,numeric,numeric,numeric,numeric,numeric)',
      'EXECUTE'
    )
  then
    raise exception 'public API roles can execute the server-only outcome RPC';
  end if;

  if not pg_catalog.has_function_privilege(
    'service_role',
    'public.twss_v20_evaluate_signal_outcomes(date,text,text,integer,numeric,numeric,numeric,numeric,numeric,numeric)',
    'EXECUTE'
  ) then
    raise exception 'service_role cannot execute the outcome RPC';
  end if;
end
$test$;

rollback;

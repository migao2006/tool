-- PostgreSQL LEAST/GREATEST are special expressions and cannot be schema-qualified.
-- Repair the already-installed function bodies while keeping the prior migration
-- correct for clean database installations.

do $migration$
declare
  v_oid oid;
  v_definition text;
begin
  for v_oid in
    select procedure_oid
    from (
      values
        ('public.twss_v20_persist_global_context(text,jsonb,jsonb,text[])'::regprocedure::oid),
        ('public.twss_admin_operations_log(integer)'::regprocedure::oid)
    ) procedures(procedure_oid)
  loop
    select pg_catalog.pg_get_functiondef(v_oid) into v_definition;
    v_definition := pg_catalog.replace(v_definition, 'pg_catalog.greatest(', 'greatest(');
    v_definition := pg_catalog.replace(v_definition, 'pg_catalog.least(', 'least(');
    execute v_definition;
  end loop;
end
$migration$;

comment on function public.twss_v20_persist_global_context(text, jsonb, jsonb, text[]) is
  'Persists server-authenticated global context into the active v20 publication model without rewriting immutable runs.';
comment on function public.twss_admin_operations_log(integer) is
  'Administrator-only v20.2.1 operations read model with current publication, normalized completed jobs, live calibration readiness, and provider configuration status.';

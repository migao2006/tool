-- v20.2.1: keep Fugle credentials server-side, repair global-context targeting,
-- and make administrator/repair states reflect the current immutable release.

create or replace function public.twss_v20_internal_provider_config()
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
  select pg_catalog.jsonb_build_object(
    'fugleMarketDataApiKey', coalesce((
      select s.decrypted_secret
      from vault.decrypted_secrets s
      where s.name = 'fugle_marketdata_api_key'
      order by s.updated_at desc
      limit 1
    ), ''),
    'fugleConfigured', exists (
      select 1 from vault.secrets s where s.name = 'fugle_marketdata_api_key'
    )
  );
$$;

revoke all on function public.twss_v20_internal_provider_config()
  from public, anon, authenticated;
grant execute on function public.twss_v20_internal_provider_config()
  to service_role;

comment on function public.twss_v20_internal_provider_config() is
  'Service-role-only provider configuration. Never grant this decrypted Vault boundary to browser roles.';

create or replace function public.twss_v20_persist_global_context(
  p_token text,
  p_global_context jsonb,
  p_source_dates jsonb default '{}'::jsonb,
  p_degraded_sources text[] default '{}'
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_expected_hash text;
  v_complete boolean;
  v_target_date date;
  v_target_model text;
  v_existing_sources text[] := '{}';
  v_sources text[] := '{}';
  v_result jsonb;
begin
  select s.decrypted_secret into v_expected_hash
  from vault.decrypted_secrets s
  where s.name = 'twss_v20_internal_key_hash'
  order by s.updated_at desc
  limit 1;

  if v_expected_hash is null
    or pg_catalog.encode(extensions.digest(coalesce(p_token, ''), 'sha256'), 'hex') <> v_expected_hash then
    raise exception 'not authorized' using errcode = '42501';
  end if;

  if pg_catalog.jsonb_typeof(p_global_context) <> 'object'
    or pg_catalog.jsonb_typeof(coalesce(p_source_dates, '{}'::jsonb)) <> 'object'
    or pg_catalog.octet_length(p_global_context::text) > 100000 then
    raise exception 'invalid global market payload' using errcode = '22023';
  end if;

  v_complete := p_global_context ?& array[
    'nasdaq', 'sp500', 'sox', 'tsmAdr', 'nvidia', 'vix', 'us10y', 'usdTwd'
  ];

  select r.data_date, r.model_version
  into v_target_date, v_target_model
  from public.v20_publication_head h
  join public.v20_recommendation_runs r on r.id = h.run_id
  where h.audience = 'public' and r.status = 'published'
  limit 1;

  if v_target_date is null then
    select c.data_date, c.model_version
    into v_target_date, v_target_model
    from public.v20_market_context c
    order by c.data_date desc, c.updated_at desc
    limit 1;
  end if;

  select coalesce(c.degraded_sources, '{}')
  into v_existing_sources
  from public.v20_market_context c
  where c.data_date = v_target_date and c.model_version = v_target_model;

  if not found then
    raise exception 'v20 market context not found' using errcode = 'P0002';
  end if;

  select coalesce(pg_catalog.array_agg(source order by source), '{}')
  into v_sources
  from (
    select distinct source
    from (
      select source
      from pg_catalog.unnest(v_existing_sources) source
      where (source <> 'international_context' or not v_complete)
        and source not like 'global\_%' escape '\'
        and source not like 'finnhub:%'
        and source not like 'alpha-vantage:%'
      union all
      select source from pg_catalog.unnest(coalesce(p_degraded_sources, '{}')) source
    ) combined
    where source is not null and source <> ''
  ) normalized;

  update public.v20_market_context c
  set global_context = coalesce(c.global_context, '{}'::jsonb) || p_global_context,
      source_dates = coalesce(c.source_dates, '{}'::jsonb) || coalesce(p_source_dates, '{}'::jsonb),
      degraded_sources = v_sources,
      completeness = greatest(0, 100 - pg_catalog.cardinality(v_sources) * 12.5),
      confidence = least(90, greatest(0, 100 - pg_catalog.cardinality(v_sources) * 12.5)),
      status = case when pg_catalog.cardinality(v_sources) = 0 then 'complete' else 'partial' end,
      updated_at = pg_catalog.now()
  where c.data_date = v_target_date and c.model_version = v_target_model
  returning pg_catalog.jsonb_build_object(
    'dataDate', c.data_date,
    'modelVersion', c.model_version,
    'updatedAt', c.updated_at,
    'complete', pg_catalog.cardinality(v_sources) = 0
  ) into v_result;

  return v_result;
end;
$$;

revoke all on function public.twss_v20_persist_global_context(text, jsonb, jsonb, text[])
  from public, anon, authenticated;
grant execute on function public.twss_v20_persist_global_context(text, jsonb, jsonb, text[])
  to service_role;

-- A successful empty margin response is an informational source limitation,
-- not an endlessly retryable repair. Depositary receipts do not have a
-- comparable domestic quarterly statement feed either.
update public.stock_analysis_cache a
set analysis = pg_catalog.jsonb_set(
      pg_catalog.jsonb_set(a.analysis, '{sourceDiagnostics,margin,status}', '"source-not-available"'::jsonb, true),
      '{sourceDiagnostics,margin,retryable}', 'false'::jsonb, true
    ),
    repair_reasons = pg_catalog.array_remove(coalesce(a.repair_reasons, '{}'), 'margin'),
    needs_repair = pg_catalog.cardinality(
      pg_catalog.array_remove(coalesce(a.repair_reasons, '{}'), 'margin')
    ) > 0,
    updated_at = pg_catalog.now()
where a.analysis #>> '{sourceDiagnostics,margin,status}' = 'empty-no-history';

update public.stock_analysis_cache a
set analysis = pg_catalog.jsonb_set(
      pg_catalog.jsonb_set(
        pg_catalog.jsonb_set(
          pg_catalog.jsonb_set(
            pg_catalog.jsonb_set(
              pg_catalog.jsonb_set(a.analysis,
                '{sourceDiagnostics,income,status}', '"source-not-applicable"'::jsonb, true),
              '{sourceDiagnostics,income,retryable}', 'false'::jsonb, true),
            '{sourceDiagnostics,balance,status}', '"source-not-applicable"'::jsonb, true),
          '{sourceDiagnostics,balance,retryable}', 'false'::jsonb, true),
        '{sourceDiagnostics,cashflow,status}', '"source-not-applicable"'::jsonb, true),
      '{sourceDiagnostics,cashflow,retryable}', 'false'::jsonb, true),
    repair_reasons = pg_catalog.array_remove(
      pg_catalog.array_remove(
        pg_catalog.array_remove(
          pg_catalog.array_remove(coalesce(a.repair_reasons, '{}'), 'income'),
          'balance'),
        'cashflow'),
      'financial-source-coverage'),
    needs_repair = false,
    updated_at = pg_catalog.now()
where a.symbol ~ '^91[0-9]{2}$'
   or coalesce(a.stock ->> 'name', '') ~* 'DR$';

do $$
begin
  if pg_catalog.to_regprocedure('public.twss_admin_operations_log_v220_base(integer)') is null then
    alter function public.twss_admin_operations_log(integer)
      rename to twss_admin_operations_log_v220_base;
  end if;
end
$$;

revoke all on function public.twss_admin_operations_log_v220_base(integer)
  from public, anon, authenticated;
grant execute on function public.twss_admin_operations_log_v220_base(integer)
  to service_role;

create or replace function public.twss_admin_operations_log(p_limit integer default 60)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  v_payload jsonb;
  v_jobs jsonb := '[]'::jsonb;
  v_model_version text;
  v_model_symbols integer := 0;
  v_sample_count integer := 0;
  v_performance_status text := 'collecting';
  v_short_ready integer := 0;
  v_medium_ready integer := 0;
  v_failed_jobs integer := 0;
  v_model text;
  v_channel text;
begin
  if (select auth.uid()) is null or not (select public.twss_is_admin()) then
    raise exception using errcode = '42501', message = 'admin_required';
  end if;

  v_payload := public.twss_admin_operations_log_v220_base(
    greatest(1, least(coalesce(p_limit, 60), 100))
  );

  select r.model_version, r.scored_symbol_count
  into v_model_version, v_model_symbols
  from public.v20_publication_head h
  join public.v20_recommendation_runs r on r.id = h.run_id
  where h.audience = 'public' and r.status = 'published'
  limit 1;

  select coalesce(pg_catalog.jsonb_agg(
    case
      when coalesce((item ->> 'total')::integer, 0) > 0
       and coalesce((item ->> 'processed')::integer, 0) >= coalesce((item ->> 'total')::integer, 0)
       and coalesce(item ->> 'lastErrorCode', '') = ''
       and coalesce(item ->> 'lastErrorPreview', '') = ''
      then item || pg_catalog.jsonb_build_object('status', 'success', 'progress', 100)
      else item
    end order by ordinal
  ), '[]'::jsonb)
  into v_jobs
  from pg_catalog.jsonb_array_elements(coalesce(v_payload -> 'jobs', '[]'::jsonb))
    with ordinality rows(item, ordinal);

  select pg_catalog.count(*)::integer into v_failed_jobs
  from pg_catalog.jsonb_array_elements(v_jobs) row
  where row ->> 'status' = 'error';

  v_sample_count := coalesce((v_payload #>> '{modelObservability,validation,sampleCount}')::integer, 0);
  v_performance_status := case when v_sample_count >= 100 then 'ready' else 'collecting' end;

  with required(model_key, horizon_days) as (
    values ('short'::text, 2), ('short', 3), ('short', 5), ('short', 10),
           ('medium', 10), ('medium', 20), ('medium', 40)
  ), totals as (
    select b.model_key, b.horizon_days, pg_catalog.sum(b.sample_count)::integer as samples
    from public.v20_calibration_buckets b
    where b.model_version = coalesce(v_model_version, b.model_version)
    group by b.model_key, b.horizon_days
  )
  select
    pg_catalog.count(*) filter (where r.model_key = 'short' and coalesce(t.samples, 0) >= 100)::integer,
    pg_catalog.count(*) filter (where r.model_key = 'medium' and coalesce(t.samples, 0) >= 100)::integer
  into v_short_ready, v_medium_ready
  from required r
  left join totals t using (model_key, horizon_days);

  v_payload := pg_catalog.jsonb_set(v_payload, '{version}', '"20.2.1"'::jsonb, true);
  v_payload := pg_catalog.jsonb_set(v_payload, '{jobs}', v_jobs, true);
  v_payload := pg_catalog.jsonb_set(v_payload, '{summary,v20ModelSymbols}', pg_catalog.to_jsonb(coalesce(v_model_symbols, 0)), true);
  v_payload := pg_catalog.jsonb_set(v_payload, '{summary,failedJobs}', pg_catalog.to_jsonb(v_failed_jobs), true);
  v_payload := pg_catalog.jsonb_set(v_payload, '{calibrationReadiness,ready}',
    pg_catalog.to_jsonb(v_short_ready = 4 and v_medium_ready = 3), true);
  v_payload := pg_catalog.jsonb_set(v_payload, '{calibrationReadiness,byModel,short,ready}',
    pg_catalog.to_jsonb(v_short_ready = 4), true);
  v_payload := pg_catalog.jsonb_set(v_payload, '{calibrationReadiness,byModel,short,readyHorizons}',
    pg_catalog.to_jsonb(v_short_ready), true);
  v_payload := pg_catalog.jsonb_set(v_payload, '{calibrationReadiness,byModel,short,requiredHorizons}', '4'::jsonb, true);
  v_payload := pg_catalog.jsonb_set(v_payload, '{calibrationReadiness,byModel,medium,ready}',
    pg_catalog.to_jsonb(v_medium_ready = 3), true);
  v_payload := pg_catalog.jsonb_set(v_payload, '{calibrationReadiness,byModel,medium,readyHorizons}',
    pg_catalog.to_jsonb(v_medium_ready), true);
  v_payload := pg_catalog.jsonb_set(v_payload, '{calibrationReadiness,byModel,medium,requiredHorizons}', '3'::jsonb, true);
  v_payload := pg_catalog.jsonb_set(v_payload, '{modelObservability,schemaVersion}', '"20.2"'::jsonb, true);
  v_payload := pg_catalog.jsonb_set(v_payload, '{modelObservability,performanceStatus}',
    pg_catalog.to_jsonb(v_performance_status), true);
  v_payload := pg_catalog.jsonb_set(v_payload, '{modelObservability,performanceMetricsAvailable}',
    pg_catalog.to_jsonb(v_performance_status = 'ready'), true);
  v_payload := pg_catalog.jsonb_set(v_payload, '{summary,modelPerformanceStatus}',
    pg_catalog.to_jsonb(v_performance_status), true);
  v_payload := pg_catalog.jsonb_set(v_payload, '{providers}', pg_catalog.jsonb_build_object(
    'fugle', pg_catalog.jsonb_build_object(
      'configured', exists (select 1 from vault.secrets s where s.name = 'fugle_marketdata_api_key'),
      'scope', 'server_only_quote_fallback'
    )
  ), true);

  foreach v_model in array array['short', 'medium'] loop
    foreach v_channel in array array['champion', 'challenger'] loop
      if v_payload #> array['modelObservability', 'channels', v_model, v_channel] is not null then
        v_payload := pg_catalog.jsonb_set(
          v_payload,
          array['modelObservability', 'channels', v_model, v_channel, 'performanceStatus'],
          pg_catalog.to_jsonb(v_performance_status),
          true
        );
      end if;
    end loop;
  end loop;

  return v_payload;
end;
$$;

revoke all on function public.twss_admin_operations_log(integer)
  from public, anon, authenticated;
grant execute on function public.twss_admin_operations_log(integer)
  to authenticated, service_role;

comment on function public.twss_admin_operations_log(integer) is
  'Administrator-only v20.2.1 operations read model with current publication, normalized completed jobs, live calibration readiness, and provider configuration status.';

-- Persist the Vercel-refreshed international market snapshot in the existing
-- v20 read model. No legacy tables or project responsibilities are changed.

do $$
begin
  if not exists (select 1 from vault.secrets where name = 'twss_v20_internal_key_hash') then
    perform vault.create_secret(
      encode(extensions.gen_random_bytes(32), 'hex'),
      'twss_v20_internal_key_hash',
      'SHA-256 hash for the narrow v20 global market cache writer'
    );
  end if;
end
$$;

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
  v_result jsonb;
begin
  select decrypted_secret
  into v_expected_hash
  from vault.decrypted_secrets
  where name = 'twss_v20_internal_key_hash';

  if v_expected_hash is null
    or encode(extensions.digest(coalesce(p_token, ''), 'sha256'), 'hex') <> v_expected_hash then
    raise exception 'not authorized' using errcode = '42501';
  end if;

  if jsonb_typeof(p_global_context) <> 'object'
    or jsonb_typeof(coalesce(p_source_dates, '{}'::jsonb)) <> 'object'
    or octet_length(p_global_context::text) > 100000 then
    raise exception 'invalid global market payload' using errcode = '22023';
  end if;

  v_complete := p_global_context ?& array[
    'nasdaq', 'sp500', 'sox', 'tsmAdr', 'nvidia', 'vix', 'us10y', 'usdTwd'
  ];

  with target as (
    select data_date, model_version
    from public.v20_market_context
    where model_version = '20.0'
    order by data_date desc
    limit 1
  ), updated as (
    update public.v20_market_context as context
    set global_context = coalesce(context.global_context, '{}'::jsonb) || p_global_context,
        source_dates = coalesce(context.source_dates, '{}'::jsonb) || coalesce(p_source_dates, '{}'::jsonb),
        degraded_sources = array(
          select distinct source
          from (
            select source
            from unnest(coalesce(context.degraded_sources, '{}')) as source
            where (source <> 'international_context' or not v_complete)
              and source not like 'global\_%' escape '\'
              and source not like 'finnhub:%'
              and source not like 'alpha-vantage:%'
            union all
            select source
            from unnest(coalesce(p_degraded_sources, '{}')) as source
          ) as sources
          where source is not null and source <> ''
        )
    from target
    where context.data_date = target.data_date
      and context.model_version = target.model_version
    returning context.data_date, context.updated_at
  )
  select jsonb_build_object('dataDate', data_date, 'updatedAt', updated_at)
  into v_result
  from updated;

  if v_result is null then
    raise exception 'v20 market context not found' using errcode = 'P0002';
  end if;
  return v_result;
end
$$;

revoke all on function public.twss_v20_persist_global_context(text, jsonb, jsonb, text[]) from public;
grant execute on function public.twss_v20_persist_global_context(text, jsonb, jsonb, text[]) to anon, authenticated;

comment on function public.twss_v20_persist_global_context(text, jsonb, jsonb, text[]) is
  'Narrow authenticated writer for the latest v20 global market cache only.';

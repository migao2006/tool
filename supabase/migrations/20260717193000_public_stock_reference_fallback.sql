-- Bounded, sanitized fallback for a stock that is outside the current immutable
-- recommendation run. This never changes the run and never exposes provider keys.

create or replace function public.twss_v20_public_stock_reference(p_symbol text)
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
  with publication as (
    select r.data_date
    from public.v20_publication_head h
    join public.v20_recommendation_runs r on r.id = h.run_id
    where h.audience = 'public' and r.status = 'published'
    limit 1
  ), latest_snapshot as (
    select s.*
    from public.stock_snapshots s
    cross join publication p
    where p_symbol ~ '^[0-9]{4,6}[A-Z]?$'
      and s.symbol = p_symbol
      and s.trade_date <= p.data_date
    order by s.trade_date desc, s.updated_at desc
    limit 1
  ), latest_signal_batch as (
    select s.signal_date, s.model_version
    from public.v20_model_signals s
    cross join publication p
    where p_symbol ~ '^[0-9]{4,6}[A-Z]?$'
      and s.symbol = p_symbol
      and s.signal_date <= p.data_date
      and s.research_only is not true
    order by s.signal_date desc, s.updated_at desc
    limit 1
  ), safe_signals as (
    select coalesce(pg_catalog.jsonb_agg(
      (
        pg_catalog.to_jsonb(s)
        - 'up_probability'
        - 'expected_return_net'
        - 'return_p10'
        - 'return_p50'
        - 'return_p90'
        - 'mfe'
        - 'mae'
        - 'target_first_probability'
      ) || pg_catalog.jsonb_build_object(
        'outside_publication', true,
        'reference_only', true
      )
      order by s.model_key, s.horizon_days
    ), '[]'::jsonb) as rows
    from public.v20_model_signals s
    join latest_signal_batch b
      on b.signal_date = s.signal_date and b.model_version = s.model_version
    where s.symbol = p_symbol and s.research_only is not true
  )
  select pg_catalog.jsonb_build_object(
    'snapshot', coalesce((
      select pg_catalog.jsonb_build_object(
        'stock', pg_catalog.jsonb_build_object(
          'symbol', s.symbol,
          'name', coalesce(nullif(s.raw_data ->> 'name', ''), s.symbol),
          'market', s.market,
          'industry', s.industry,
          'instrumentType', s.instrument_type,
          'priceDate', s.trade_date,
          'close', s.close
        ),
        'quote', case when s.close is null then null else pg_catalog.jsonb_build_object(
          'tradeDate', s.trade_date,
          'close', s.close,
          'change', s.change_pct,
          'open', s.open,
          'high', s.high,
          'low', s.low,
          'volume', s.volume,
          'value', s.trade_value,
          'source', coalesce(s.source, 'stored market snapshot')
        ) end,
        'sourceDates', coalesce(s.source_dates, '{}'::jsonb),
        'fetchedAt', s.updated_at
      )
      from latest_snapshot s
    ), '{}'::jsonb),
    'signals', (select rows from safe_signals)
  );
$$;

revoke all on function public.twss_v20_public_stock_reference(text)
  from public, anon, authenticated, service_role;
grant execute on function public.twss_v20_public_stock_reference(text)
  to anon, authenticated, service_role;

comment on function public.twss_v20_public_stock_reference(text) is
  'One-symbol sanitized quote and prior-model reference fallback. It is explicitly outside the current immutable recommendation publication.';

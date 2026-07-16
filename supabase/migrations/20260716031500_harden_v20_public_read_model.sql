-- v20 read-model hardening: keep ranking rows public-only while allowing one
-- sanitized per-symbol analysis lookup, pin public aggregates to model 20.0,
-- and give the bounded model worker enough post-close capacity.

create or replace function public.twss_v20_public_stock_signals(
  p_symbol text,
  p_model_version text default '20.0'
)
returns setof public.v20_model_signals
language sql
stable
security definer
set search_path = ''
as $$
  select s.*
  from public.v20_model_signals s
  where p_symbol ~ '^[0-9]{4,6}[A-Z]?$'
    and p_model_version = '20.0'
    and s.symbol = p_symbol
    and s.model_version = p_model_version
    and s.signal_date = (
      select max(latest.signal_date)
      from public.v20_model_signals latest
      where latest.symbol = p_symbol
        and latest.model_version = p_model_version
    )
  order by s.model_key, s.horizon_days
  limit 8;
$$;

revoke all on function public.twss_v20_public_stock_signals(text, text)
  from public, anon, authenticated;
grant execute on function public.twss_v20_public_stock_signals(text, text)
  to anon, authenticated, service_role;

comment on function public.twss_v20_public_stock_signals(text, text) is
  'Bounded one-symbol v20 read model. Ranking RLS remains official-only; this RPC enables risk/data-insufficient detail without exposing bulk rejected signals.';

-- The earlier generic aggregate remains available to service_role only. The
-- public v20 endpoint uses this model-pinned function so future model rows can
-- never be mixed into a 20.0 response.
revoke execute on function public.twss_v20_public_backtest_summary(text, integer, text, text, text)
  from anon, authenticated;

create or replace function public.twss_v20_public_backtest_summary_v20(
  p_model_key text default null,
  p_horizon_days integer default null,
  p_strategy_key text default null,
  p_regime text default null,
  p_industry text default null
)
returns table (
  model_key text,
  horizon_days integer,
  strategy_key text,
  regime text,
  industry text,
  sample_count bigint,
  win_rate numeric,
  average_net_return numeric,
  median_net_return numeric,
  average_mfe numeric,
  average_mae numeric,
  calibration_error numeric,
  generated_at timestamptz
)
language sql
stable
security definer
set search_path = ''
as $$
  select
    o.model_key,
    o.horizon_days,
    o.strategy_key,
    o.market_regime as regime,
    coalesce(o.industry, 'unknown') as industry,
    count(*)::bigint as sample_count,
    round(100 * avg(case when o.net_return > 0 then 1 else 0 end)::numeric, 2) as win_rate,
    round(avg(o.net_return)::numeric, 4) as average_net_return,
    round((pg_catalog.percentile_cont(0.5) within group (order by o.net_return))::numeric, 4) as median_net_return,
    round(avg(o.mfe)::numeric, 4) as average_mfe,
    round(avg(o.mae)::numeric, 4) as average_mae,
    round((100 * avg(
      abs((o.up_probability / 100) - case when o.net_return > 0 then 1 else 0 end)
    ) filter (where o.up_probability is not null))::numeric, 4) as calibration_error,
    max(coalesce(o.evaluated_at, r.completed_at, o.created_at)) as generated_at
  from public.v20_backtest_outcomes o
  join public.v20_backtest_runs r on r.id = o.run_id and r.status = 'complete'
  where o.model_version = '20.0'
    and r.model_version = '20.0'
    and (p_model_key is null or o.model_key = p_model_key)
    and (p_horizon_days is null or o.horizon_days = p_horizon_days)
    and (p_strategy_key is null or o.strategy_key = p_strategy_key)
    and (p_regime is null or o.market_regime = p_regime)
    and (p_industry is null or coalesce(o.industry, 'unknown') = p_industry)
  group by o.model_key, o.horizon_days, o.strategy_key, o.market_regime, coalesce(o.industry, 'unknown')
  order by sample_count desc, o.model_key, o.horizon_days, o.strategy_key
  limit 500;
$$;

revoke all on function public.twss_v20_public_backtest_summary_v20(text, integer, text, text, text)
  from public, anon, authenticated;
grant execute on function public.twss_v20_public_backtest_summary_v20(text, integer, text, text, text)
  to anon, authenticated, service_role;

do $$
declare
  existing_job bigint;
begin
  for existing_job in
    select jobid from cron.job where jobname = 'twss-v20-model-weekday'
  loop
    perform cron.unschedule(existing_job);
  end loop;
end
$$;

select cron.schedule(
  'twss-v20-model-weekday',
  '*/5 7-13 * * 1-5',
  $job$
    select net.http_post(
      url := 'https://lfkdkdyaatdlizryiyon.supabase.co/functions/v1/twss-v20-model',
      headers := jsonb_build_object(
        'Content-Type', 'application/json',
        'x-twss-sync-token', (
          select decrypted_secret from vault.decrypted_secrets where name = 'twss_sync_token'
        )
      ),
      body := '{"limit":100}'::jsonb,
      timeout_milliseconds := 300000
    );
  $job$
);

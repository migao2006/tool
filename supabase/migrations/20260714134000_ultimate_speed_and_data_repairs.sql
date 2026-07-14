-- v16.3: run immediately below FinMind's unauthenticated 300 requests/hour
-- ceiling while keeping every Edge Function comfortably below the Free-plan
-- 150-second wall-clock limit.
--
-- Each invocation requests the maximum reusable-history batch (22/22/23).
-- Runtime uses fair per-job request slices: 50/50/19 without a token and
-- 88/88/23 with a token. A cold company costs 8 requests (6 or 11 symbols);
-- a company whose monthly/quarterly history is reusable costs 4 (10 or 22).
-- The later sliding-window quota migration atomically caps all jobs, manual
-- runs and benchmark fallbacks at the documented 300/600 calls per 60 minutes.

do $$
declare
  existing_job bigint;
begin
  for existing_job in
    select jobid
    from cron.job
    where jobname in ('twss-deep-listed', 'twss-deep-otc', 'twss-deep-etf')
  loop
    perform cron.unschedule(existing_job);
  end loop;
end
$$;

select cron.schedule(
  'twss-deep-listed',
  '1,21,41 * * * *',
  $job$
    select net.http_post(
      url := 'https://lfkdkdyaatdlizryiyon.supabase.co/functions/v1/twss-sync-batch',
      headers := jsonb_build_object(
        'Content-Type', 'application/json',
        'x-twss-sync-token', (
          select decrypted_secret from vault.decrypted_secrets where name = 'twss_sync_token'
        )
      ),
      body := '{"mode":"deep","group":"listed","limit":22}'::jsonb,
      timeout_milliseconds := 300000
    );
  $job$
);

select cron.schedule(
  'twss-deep-otc',
  '8,28,48 * * * *',
  $job$
    select net.http_post(
      url := 'https://lfkdkdyaatdlizryiyon.supabase.co/functions/v1/twss-sync-batch',
      headers := jsonb_build_object(
        'Content-Type', 'application/json',
        'x-twss-sync-token', (
          select decrypted_secret from vault.decrypted_secrets where name = 'twss_sync_token'
        )
      ),
      body := '{"mode":"deep","group":"otc","limit":22}'::jsonb,
      timeout_milliseconds := 300000
    );
  $job$
);

select cron.schedule(
  'twss-deep-etf',
  '15,35,55 * * * *',
  $job$
    select net.http_post(
      url := 'https://lfkdkdyaatdlizryiyon.supabase.co/functions/v1/twss-sync-batch',
      headers := jsonb_build_object(
        'Content-Type', 'application/json',
        'x-twss-sync-token', (
          select decrypted_secret from vault.decrypted_secrets where name = 'twss_sync_token'
        )
      ),
      body := '{"mode":"deep","group":"etf","limit":23}'::jsonb,
      timeout_milliseconds := 300000
    );
  $job$
);

-- Existing detailed rows already contain the correct monthly and quarterly
-- amounts in normalized tables.  Repair the compact JSON immediately so users
-- do not have to wait for every symbol to be revalidated by v16.3.
with latest_revenue as (
  select distinct on (symbol)
    symbol, revenue_period, revenue, mom, yoy
  from public.stock_monthly_revenues
  order by symbol, revenue_period desc
)
update public.stock_analysis_cache as cache
set stock = coalesce(cache.stock, '{}'::jsonb) || jsonb_build_object(
      'revenue', latest.revenue,
      'rev', latest.yoy,
      'revMom', latest.mom,
      'revPeriod', latest.revenue_period,
      'revenueUnit', 'TWD'
    ),
    updated_at = now()
from latest_revenue as latest
where cache.symbol = latest.symbol
  and cache.status = 'ready';

with latest_financial as (
  select distinct on (symbol)
    symbol, revenue
  from public.stock_quarterly_financials
  where revenue is not null
  order by symbol, report_date desc nulls last, report_period desc
)
update public.stock_analysis_cache as cache
set analysis = coalesce(cache.analysis, '{}'::jsonb) || jsonb_build_object(
      'financial', coalesce(cache.analysis->'financial', '{}'::jsonb) ||
        jsonb_build_object('revenue', latest.revenue)
    ),
    updated_at = now()
from latest_financial as latest
where cache.symbol = latest.symbol
  and cache.status = 'ready';

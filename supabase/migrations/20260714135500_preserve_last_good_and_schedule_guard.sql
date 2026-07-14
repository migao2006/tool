-- Preserve the last successful analysis when a later refresh fails, and keep
-- the universe transaction from racing the first deep group.

alter table public.stock_analysis_cache
  add column if not exists last_attempt_at timestamptz;

create index if not exists stock_analysis_cache_refresh_idx
  on public.stock_analysis_cache (group_name, fetched_at)
  where status = 'ready';

do $$
declare
  existing_job bigint;
begin
  for existing_job in
    select jobid from cron.job where jobname = 'twss-universe-weekday'
  loop
    perform cron.unschedule(existing_job);
  end loop;
end
$$;

-- 06:43 UTC = 14:43 Asia/Taipei.  The first deep job is at :48 and the Edge
-- Function also checks the universe lease, so a slow upstream response cannot
-- expose a half-written cycle.
select cron.schedule(
  'twss-universe-weekday',
  '43 6 * * 1-5',
  $job$
    select net.http_post(
      url := 'https://lfkdkdyaatdlizryiyon.supabase.co/functions/v1/twss-sync-batch',
      headers := jsonb_build_object(
        'Content-Type', 'application/json',
        'x-twss-sync-token', (
          select decrypted_secret from vault.decrypted_secrets where name = 'twss_sync_token'
        )
      ),
      body := '{"mode":"universe"}'::jsonb,
      timeout_milliseconds := 300000
    );
  $job$
);

-- Invoke the protected batch updater in small, non-overlapping jobs.
-- pg_cron uses UTC: 06:45 UTC is 14:45 in Taiwan.

do $$
declare
  existing_job bigint;
begin
  for existing_job in
    select jobid from cron.job
    where jobname in (
      'twss-universe-weekday',
      'twss-deep-listed',
      'twss-deep-otc',
      'twss-deep-etf'
    )
  loop
    perform cron.unschedule(existing_job);
  end loop;
end
$$;

select cron.schedule(
  'twss-universe-weekday',
  '45 6 * * 1-5',
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

select cron.schedule(
  'twss-deep-listed',
  '5,35 * * * *',
  $job$
    select net.http_post(
      url := 'https://lfkdkdyaatdlizryiyon.supabase.co/functions/v1/twss-sync-batch',
      headers := jsonb_build_object(
        'Content-Type', 'application/json',
        'x-twss-sync-token', (
          select decrypted_secret from vault.decrypted_secrets where name = 'twss_sync_token'
        )
      ),
      body := '{"mode":"deep","group":"listed","limit":2}'::jsonb,
      timeout_milliseconds := 300000
    );
  $job$
);

select cron.schedule(
  'twss-deep-otc',
  '15,45 * * * *',
  $job$
    select net.http_post(
      url := 'https://lfkdkdyaatdlizryiyon.supabase.co/functions/v1/twss-sync-batch',
      headers := jsonb_build_object(
        'Content-Type', 'application/json',
        'x-twss-sync-token', (
          select decrypted_secret from vault.decrypted_secrets where name = 'twss_sync_token'
        )
      ),
      body := '{"mode":"deep","group":"otc","limit":2}'::jsonb,
      timeout_milliseconds := 300000
    );
  $job$
);

select cron.schedule(
  'twss-deep-etf',
  '25,55 * * * *',
  $job$
    select net.http_post(
      url := 'https://lfkdkdyaatdlizryiyon.supabase.co/functions/v1/twss-sync-batch',
      headers := jsonb_build_object(
        'Content-Type', 'application/json',
        'x-twss-sync-token', (
          select decrypted_secret from vault.decrypted_secrets where name = 'twss_sync_token'
        )
      ),
      body := '{"mode":"deep","group":"etf","limit":2}'::jsonb,
      timeout_milliseconds := 300000
    );
  $job$
);

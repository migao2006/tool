-- Increase first-cycle coverage while staying below the unauthenticated
-- FinMind allowance. Jobs remain staggered so only one deep batch normally
-- runs at a time; the Edge Function still applies its per-source pacing.

do $$
declare
  existing_job bigint;
begin
  for existing_job in
    select jobid
    from cron.job
    where jobname in (
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
      body := '{"mode":"deep","group":"listed","limit":3}'::jsonb,
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
      body := '{"mode":"deep","group":"otc","limit":3}'::jsonb,
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
      body := '{"mode":"deep","group":"etf","limit":3}'::jsonb,
      timeout_milliseconds := 300000
    );
  $job$
);

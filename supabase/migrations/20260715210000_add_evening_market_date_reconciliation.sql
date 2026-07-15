-- v17.3.1: the first post-close run can precede the official TWSE/TPEx
-- publication rollover.  Reconcile twice more after publication windows so
-- the durable universe and the browser's official snapshot converge on the
-- same trading date.  The worker lease and UPSERT keys keep these retries
-- idempotent and prevent overlapping universe writes.

do $$
declare
  existing_job bigint;
begin
  for existing_job in
    select jobid
    from cron.job
    where jobname = 'twss-universe-evening-reconcile'
  loop
    perform cron.unschedule(existing_job);
  end loop;
end
$$;

-- pg_cron uses UTC: 09:10 and 13:10 are 17:10 and 21:10 in Asia/Taipei.
-- Keeping the 14:43 first pass makes preliminary data available early; these
-- later passes correct an upstream source that was still on the prior date.
select cron.schedule(
  'twss-universe-evening-reconcile',
  '10 9,13 * * 1-5',
  $job$
    select net.http_post(
      url := 'https://lfkdkdyaatdlizryiyon.supabase.co/functions/v1/twss-sync-batch',
      headers := jsonb_build_object(
        'Content-Type', 'application/json',
        'x-twss-sync-token', (
          select decrypted_secret
          from vault.decrypted_secrets
          where name = 'twss_sync_token'
        )
      ),
      body := '{"mode":"universe"}'::jsonb,
      timeout_milliseconds := 300000
    );
  $job$
);

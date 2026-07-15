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

-- Expose only non-secret scheduler readiness to the authenticated administrator.
-- The UI uses this to distinguish a normal in-progress reconciliation from a
-- missing or disabled cron configuration.
create or replace function public.twss_admin_schedule_status()
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  v_universe_weekday boolean;
  v_evening_reconcile boolean;
  v_evening_schedule text;
begin
  if (select auth.uid()) is null or not (select public.twss_is_admin()) then
    raise exception using errcode = '42501', message = 'admin_required';
  end if;

  select coalesce(bool_or(j.active), false)
    into v_universe_weekday
  from cron.job j
  where j.jobname = 'twss-universe-weekday';

  select coalesce(bool_or(j.active), false), max(j.schedule)
    into v_evening_reconcile, v_evening_schedule
  from cron.job j
  where j.jobname = 'twss-universe-evening-reconcile';

  return pg_catalog.jsonb_build_object(
    'ready', v_universe_weekday and v_evening_reconcile,
    'universeWeekday', v_universe_weekday,
    'eveningReconcile', v_evening_reconcile,
    'eveningSchedule', v_evening_schedule,
    'timezone', 'UTC',
    'checkedAt', clock_timestamp()
  );
end;
$$;

revoke all on function public.twss_admin_schedule_status()
  from public, anon, authenticated;
grant execute on function public.twss_admin_schedule_status()
  to authenticated, service_role;

comment on function public.twss_admin_schedule_status() is
  'Returns only non-secret scheduler readiness for the authenticated active administrator.';

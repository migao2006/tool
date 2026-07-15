-- Keep v19 snapshots aligned with the deep-analysis workers at all hours.
-- The refresh function has an unchanged-data guard, so a five-minute check
-- does not rewrite snapshots when score history has not changed.

-- opportunity_score_history has one row per symbol/day/model and historically
-- used created_at as its row-version timestamp.  PostgREST upserts do not
-- change that column automatically, so touch it only when a provisional row
-- actually changes.  The zz_ prefix intentionally runs this after the existing
-- preserve_final_score_history trigger; finalized rows are returned as OLD and
-- therefore remain untouched.
create or replace function public.twss_v19_touch_score_history_change()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new is distinct from old then
    new.created_at := pg_catalog.clock_timestamp();
  end if;
  return new;
end;
$$;

revoke all on function public.twss_v19_touch_score_history_change()
  from public, anon, authenticated;

drop trigger if exists zz_twss_v19_touch_score_history_change
  on public.opportunity_score_history;
create trigger zz_twss_v19_touch_score_history_change
before update on public.opportunity_score_history
for each row execute function public.twss_v19_touch_score_history_change();

do $$
declare
  existing_job bigint;
begin
  for existing_job in
    select jobid from cron.job where jobname = 'twss-v19-ranking-snapshots'
  loop
    perform cron.unschedule(existing_job);
  end loop;
end
$$;

select cron.schedule(
  'twss-v19-ranking-snapshots',
  '*/5 * * * *',
  $job$select public.twss_v19_refresh_available_rankings();$job$
);

select public.twss_v19_refresh_available_rankings();

-- Operational maintenance is deliberately independent from recommendation data.
-- The web gate is enabled before cron workers are paused and is only opened for
-- signed read-only smoke tests run while the public gate stays closed; the
-- exact prior cron state and the public gate are restored together afterward.

create table if not exists public.twss_maintenance_control (
  id text primary key default 'global' check (id = 'global'),
  enabled boolean not null default false,
  phase text not null default 'off'
    check (phase in ('off', 'draining', 'maintenance', 'verifying')),
  reason text,
  actor text,
  generation bigint not null default 0 check (generation >= 0),
  cron_snapshot jsonb not null default '{}'::jsonb
    check (jsonb_typeof(cron_snapshot) = 'object'),
  enabled_at timestamptz,
  updated_at timestamptz not null default pg_catalog.clock_timestamp()
);

create table if not exists public.twss_maintenance_events (
  id bigint generated always as identity primary key,
  generation bigint not null check (generation >= 0),
  action text not null check (action in (
    'enable_web', 'pause_jobs', 'open_web', 'reclose_web', 'resume_jobs'
  )),
  actor text not null,
  reason text,
  state jsonb not null,
  created_at timestamptz not null default pg_catalog.clock_timestamp()
);

insert into public.twss_maintenance_control (
  id, enabled, phase, reason, actor, generation, enabled_at, updated_at
)
values (
  'global', true, 'draining', 'initial v20.1 verified rollout',
  'migration:20260716174105', 1, pg_catalog.clock_timestamp(), pg_catalog.clock_timestamp()
)
on conflict (id) do nothing;

insert into public.twss_maintenance_events (generation, action, actor, reason, state)
select
  c.generation,
  'enable_web',
  c.actor,
  c.reason,
  pg_catalog.to_jsonb(c) - 'cron_snapshot'
from public.twss_maintenance_control c
where c.id = 'global'
  and c.enabled
  and c.phase = 'draining'
  and c.generation = 1
  and not exists (
    select 1 from public.twss_maintenance_events e
    where e.generation = c.generation and e.action = 'enable_web'
  );

alter table public.twss_maintenance_control enable row level security;
alter table public.twss_maintenance_events enable row level security;

revoke all on table public.twss_maintenance_control from public, anon, authenticated;
revoke all on table public.twss_maintenance_events from public, anon, authenticated;
revoke all on sequence public.twss_maintenance_events_id_seq from public, anon, authenticated;

grant select on table public.twss_maintenance_control to service_role;
grant select on table public.twss_maintenance_events to service_role;

create or replace function public.twss_maintenance_reject_event_change()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $function$
begin
  raise exception 'maintenance_events_are_append_only' using errcode = '55000';
end;
$function$;

drop trigger if exists twss_maintenance_events_append_only on public.twss_maintenance_events;
create trigger twss_maintenance_events_append_only
before update or delete on public.twss_maintenance_events
for each row execute function public.twss_maintenance_reject_event_change();

revoke all on function public.twss_maintenance_reject_event_change()
  from public, anon, authenticated, service_role;

create or replace function public.twss_maintenance_enable_web(
  p_reason text,
  p_actor text default 'automation'
)
returns public.twss_maintenance_control
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor text := pg_catalog.left(coalesce(nullif(pg_catalog.btrim(p_actor), ''), 'automation'), 120);
  v_reason text := pg_catalog.left(coalesce(nullif(pg_catalog.btrim(p_reason), ''), 'planned maintenance'), 500);
  v_snapshot jsonb;
  v_control public.twss_maintenance_control;
begin
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('twss-maintenance-control', 0));

  select * into strict v_control
  from public.twss_maintenance_control
  where id = 'global'
  for update;

  if v_control.enabled and v_control.phase in ('draining', 'maintenance') then
    return v_control;
  end if;
  if v_control.enabled or v_control.phase <> 'off' then
    raise exception using errcode = '55000', message = 'maintenance transition already active';
  end if;

  select coalesce(
    pg_catalog.jsonb_object_agg(
      j.jobid::text,
      pg_catalog.jsonb_build_object('jobname', j.jobname, 'active', j.active)
      order by j.jobid
    ),
    '{}'::jsonb
  )
  into v_snapshot
  from cron.job as j;

  update public.twss_maintenance_control
  set enabled = true,
      phase = 'draining',
      reason = v_reason,
      actor = v_actor,
      generation = generation + 1,
      cron_snapshot = v_snapshot,
      enabled_at = pg_catalog.clock_timestamp(),
      updated_at = pg_catalog.clock_timestamp()
  where id = 'global'
  returning * into strict v_control;

  insert into public.twss_maintenance_events (generation, action, actor, reason, state)
  values (
    v_control.generation,
    'enable_web',
    v_actor,
    v_reason,
    pg_catalog.to_jsonb(v_control) - 'cron_snapshot'
  );

  return v_control;
end;
$function$;

create or replace function public.twss_maintenance_pause_jobs(
  p_actor text default 'automation'
)
returns public.twss_maintenance_control
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor text := pg_catalog.left(coalesce(nullif(pg_catalog.btrim(p_actor), ''), 'automation'), 120);
  v_current_snapshot jsonb;
  v_control public.twss_maintenance_control;
  v_job record;
begin
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('twss-maintenance-control', 0));
  select * into strict v_control
  from public.twss_maintenance_control
  where id = 'global'
  for update;

  if not v_control.enabled or v_control.phase not in ('draining', 'maintenance') then
    raise exception using errcode = '55000', message = 'maintenance web gate must be enabled before pausing jobs';
  end if;

  select coalesce(
    pg_catalog.jsonb_object_agg(
      j.jobid::text,
      pg_catalog.jsonb_build_object('jobname', j.jobname, 'active', j.active)
      order by j.jobid
    ),
    '{}'::jsonb
  )
  into v_current_snapshot
  from cron.job as j;

  update public.twss_maintenance_control
  -- Existing values win so a retry cannot overwrite an originally-active job
  -- with the currently-paused false value. Newly-created jobs are still added.
  set cron_snapshot = v_current_snapshot || cron_snapshot,
      updated_at = pg_catalog.clock_timestamp()
  where id = 'global'
  returning * into strict v_control;

  for v_job in
    select j.jobid
    from cron.job as j
    where j.active
    order by j.jobid
  loop
    perform cron.alter_job(v_job.jobid, active => false);
  end loop;

  update public.twss_maintenance_control
  set phase = 'maintenance',
      updated_at = pg_catalog.clock_timestamp()
  where id = 'global'
  returning * into strict v_control;

  insert into public.twss_maintenance_events (generation, action, actor, reason, state)
  values (
    v_control.generation,
    'pause_jobs',
    v_actor,
    v_control.reason,
    pg_catalog.to_jsonb(v_control) - 'cron_snapshot'
  );

  return v_control;
end;
$function$;

create or replace function public.twss_maintenance_open_web(
  p_actor text default 'automation'
)
returns public.twss_maintenance_control
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor text := pg_catalog.left(coalesce(nullif(pg_catalog.btrim(p_actor), ''), 'automation'), 120);
  v_control public.twss_maintenance_control;
begin
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('twss-maintenance-control', 0));
  select * into strict v_control
  from public.twss_maintenance_control
  where id = 'global'
  for update;

  if not v_control.enabled or v_control.phase <> 'maintenance' then
    raise exception using errcode = '55000', message = 'jobs must be paused before opening the web gate';
  end if;

  update public.twss_maintenance_control
  set enabled = true,
      phase = 'verifying',
      actor = v_actor,
      updated_at = pg_catalog.clock_timestamp()
  where id = 'global'
  returning * into strict v_control;

  insert into public.twss_maintenance_events (generation, action, actor, reason, state)
  values (v_control.generation, 'open_web', v_actor, v_control.reason, pg_catalog.to_jsonb(v_control) - 'cron_snapshot');

  return v_control;
end;
$function$;

create or replace function public.twss_maintenance_reclose_web(
  p_reason text default 'smoke verification failed',
  p_actor text default 'automation'
)
returns public.twss_maintenance_control
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor text := pg_catalog.left(coalesce(nullif(pg_catalog.btrim(p_actor), ''), 'automation'), 120);
  v_reason text := pg_catalog.left(coalesce(nullif(pg_catalog.btrim(p_reason), ''), 'smoke verification failed'), 500);
  v_control public.twss_maintenance_control;
begin
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('twss-maintenance-control', 0));
  select * into strict v_control
  from public.twss_maintenance_control
  where id = 'global'
  for update;

  if v_control.phase <> 'verifying' then
    raise exception using errcode = '55000', message = 'web gate can only be reclosed during verification';
  end if;

  update public.twss_maintenance_control
  set enabled = true,
      phase = 'maintenance',
      reason = v_reason,
      actor = v_actor,
      updated_at = pg_catalog.clock_timestamp()
  where id = 'global'
  returning * into strict v_control;

  insert into public.twss_maintenance_events (generation, action, actor, reason, state)
  values (v_control.generation, 'reclose_web', v_actor, v_reason, pg_catalog.to_jsonb(v_control) - 'cron_snapshot');

  return v_control;
end;
$function$;

create or replace function public.twss_maintenance_resume_jobs(
  p_actor text default 'automation'
)
returns public.twss_maintenance_control
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor text := pg_catalog.left(coalesce(nullif(pg_catalog.btrim(p_actor), ''), 'automation'), 120);
  v_control public.twss_maintenance_control;
  v_job record;
begin
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('twss-maintenance-control', 0));
  select * into strict v_control
  from public.twss_maintenance_control
  where id = 'global'
  for update;

  if not v_control.enabled or v_control.phase <> 'verifying' then
    raise exception using errcode = '55000', message = 'complete signed verification before resuming jobs';
  end if;

  for v_job in
    select j.jobid
    from cron.job as j
    where coalesce(
      (v_control.cron_snapshot -> j.jobid::text ->> 'active')::boolean,
      false
    )
    order by j.jobid
  loop
    perform cron.alter_job(v_job.jobid, active => true);
  end loop;

  update public.twss_maintenance_control
  set enabled = false,
      phase = 'off',
      reason = null,
      actor = v_actor,
      cron_snapshot = '{}'::jsonb,
      enabled_at = null,
      updated_at = pg_catalog.clock_timestamp()
  where id = 'global'
  returning * into strict v_control;

  insert into public.twss_maintenance_events (generation, action, actor, reason, state)
  values (v_control.generation, 'resume_jobs', v_actor, null, pg_catalog.to_jsonb(v_control) - 'cron_snapshot');

  return v_control;
end;
$function$;

create or replace function public.twss_is_maintenance()
returns boolean
language sql
stable
security invoker
set search_path = ''
as $function$
  select enabled
  from public.twss_maintenance_control
  where id = 'global'
$function$;

revoke all on function public.twss_maintenance_enable_web(text, text) from public, anon, authenticated;
revoke all on function public.twss_maintenance_pause_jobs(text) from public, anon, authenticated;
revoke all on function public.twss_maintenance_open_web(text) from public, anon, authenticated;
revoke all on function public.twss_maintenance_reclose_web(text, text) from public, anon, authenticated;
revoke all on function public.twss_maintenance_resume_jobs(text) from public, anon, authenticated;
revoke all on function public.twss_is_maintenance() from public, anon, authenticated;

grant execute on function public.twss_maintenance_enable_web(text, text) to service_role;
grant execute on function public.twss_maintenance_pause_jobs(text) to service_role;
grant execute on function public.twss_maintenance_open_web(text) to service_role;
grant execute on function public.twss_maintenance_reclose_web(text, text) to service_role;
grant execute on function public.twss_maintenance_resume_jobs(text) to service_role;
grant execute on function public.twss_is_maintenance() to service_role;

comment on table public.twss_maintenance_control is
  'Private operational switch read by Vercel middleware and workers; mutate only through service-role RPCs.';
comment on table public.twss_maintenance_events is
  'Append-only audit trail for maintenance gate and cron state transitions.';

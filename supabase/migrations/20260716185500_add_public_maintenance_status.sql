-- Expose only the non-sensitive web-gate state so Vercel middleware can read
-- maintenance mode with the public Supabase key. The control table and its
-- actor, reason, and cron snapshot remain private to service_role.

create or replace function public.twss_public_maintenance_status()
returns jsonb
language sql
stable
security definer
set search_path = ''
as $function$
  select pg_catalog.jsonb_build_object(
    'enabled', c.enabled,
    'phase', c.phase,
    'generation', c.generation,
    'updatedAt', c.updated_at
  )
  from public.twss_maintenance_control as c
  where c.id = 'global'
$function$;

revoke all on function public.twss_public_maintenance_status()
  from public;
grant execute on function public.twss_public_maintenance_status()
  to anon, authenticated, service_role;

comment on function public.twss_public_maintenance_status() is
  'Safe public read model for the production maintenance web gate.';

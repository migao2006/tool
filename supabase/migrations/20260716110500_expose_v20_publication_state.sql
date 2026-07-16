-- Sanitized public pointer for Vercel/public APIs.  No lease, error, token or
-- worker internals are exposed; stock_sync_state itself remains service-only.
create or replace function public.twss_v20_publication_state()
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
  select pg_catalog.jsonb_build_object(
    'publicationPhase', coalesce(s.details ->> 'publicationPhase', 'cached'),
    'publishedDataDate', s.details ->> 'publishedDataDate',
    'baseCompletedAt', s.details -> 'baseCompletedAt',
    'enrichmentCompletedAt', s.details -> 'enrichmentCompletedAt',
    'enrichmentPending', coalesce(s.details -> 'enrichmentPending', '0'::jsonb),
    'sourceDates', coalesce(s.details -> 'sourceDates', '{}'::jsonb),
    'dataCompleteness', coalesce(s.details -> 'dataCompleteness', '0'::jsonb),
    'publishedAt', coalesce(s.details -> 'publishedAt', s.details -> 'completedCycleAt')
  )
  from public.stock_sync_state s
  where s.job_key = 'v20_model'
  limit 1;
$$;

revoke all on function public.twss_v20_publication_state()
  from public;
grant execute on function public.twss_v20_publication_state()
  to anon, authenticated, service_role;

comment on function public.twss_v20_publication_state() is
  'Sanitized v20 atomic-publication pointer; intentionally excludes worker errors, leases and secrets.';

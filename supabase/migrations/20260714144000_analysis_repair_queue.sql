-- Keep a compact repair signal beside each last-known-good analysis.  This
-- lets scheduled batches revisit HTTP-200/empty or stale source components
-- without downloading every cached JSON analysis just to find the gaps.
alter table public.stock_analysis_cache
  add column if not exists needs_repair boolean not null default false,
  add column if not exists repair_reasons text[] not null default '{}';

update public.stock_analysis_cache
set needs_repair = true,
    repair_reasons = array['v16.3-source-coverage-audit']::text[]
where status = 'ready'
  and group_name <> 'etf'
  and analysis_version = '16.3-ultimate-data-audit'
  and (
    analysis #> '{financial,sourceCoverage}' is null
    or coalesce(analysis #>> '{sourceDiagnostics,revenue,status}', '') in ('empty-no-history', 'stale-source-period')
    or coalesce(analysis #>> '{sourceDiagnostics,income,status}', '') in ('empty-no-history', 'stale-source-period')
    or coalesce(analysis #>> '{sourceDiagnostics,balance,status}', '') in ('empty-no-history', 'stale-source-period')
    or coalesce(analysis #>> '{sourceDiagnostics,cashflow,status}', '') in ('empty-no-history', 'stale-source-period')
  );

create index if not exists idx_stock_analysis_cache_repair_queue
  on public.stock_analysis_cache (group_name, fetched_at asc)
  where status = 'ready' and needs_repair = true;

comment on column public.stock_analysis_cache.needs_repair is
  'True when an otherwise usable last-good analysis has an empty or stale essential source and should be retried.';

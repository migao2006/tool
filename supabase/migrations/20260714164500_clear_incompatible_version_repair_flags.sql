-- Older model versions are already selected as unseen by the v16.3 worker.
-- They do not belong in the v16.3 last-good repair counter as well.
update public.stock_analysis_cache
set needs_repair = false,
    repair_reasons = '{}'::text[]
where analysis_version <> '16.3-ultimate-data-audit'
  and needs_repair = true;

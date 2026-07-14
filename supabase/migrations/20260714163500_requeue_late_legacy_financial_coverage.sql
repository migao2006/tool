-- Some rows were written by an older Edge isolate after the initial v16.3
-- audit migration but before the new function version became active.  They
-- have usable last-good numbers yet no per-source coverage, so re-fetch them
-- once and let the new diagnostics decide whether a missing quarterly revenue
-- field is recoverable or genuinely absent upstream.
update public.stock_analysis_cache
set needs_repair = true,
    repair_reasons = array_append(
      array_remove(repair_reasons, 'financial-source-coverage'),
      'financial-source-coverage'
    )
where group_name <> 'etf'
  and status = 'ready'
  and analysis_version = '16.3-ultimate-data-audit'
  and (
    coalesce((analysis #>> '{financial,sourceCoverage,incomeRows}')::integer, 0) <= 0
    or coalesce((analysis #>> '{financial,sourceCoverage,balanceRows}')::integer, 0) <= 0
    or coalesce((analysis #>> '{financial,sourceCoverage,cashflowRows}')::integer, 0) <= 0
  );

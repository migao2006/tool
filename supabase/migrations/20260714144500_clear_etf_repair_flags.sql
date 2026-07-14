-- ETF analysis intentionally has no company revenue, balance sheet or cash
-- flow.  Never enqueue those not-applicable fields as company-data repairs.
update public.stock_analysis_cache
set needs_repair = false,
    repair_reasons = '{}'::text[]
where group_name = 'etf'
  and needs_repair = true;

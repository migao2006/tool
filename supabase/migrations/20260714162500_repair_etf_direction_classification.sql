-- MOPS uses the umbrella fund type `槓桿/反向指數股票型基金` for
-- both positive-leverage and inverse ETFs.  Earlier v16.3 rows therefore
-- classified 11 long 2x ETFs as both leveraged and inverse.  Re-run only
-- affected last-good rows; persistDeep clears the flag after recomputation.
update public.stock_analysis_cache
set needs_repair = true,
    repair_reasons = array['etf-direction-classification']::text[]
where group_name = 'etf'
  and status = 'ready'
  and coalesce((analysis #>> '{etf,leveraged}')::boolean, false)
  and coalesce((analysis #>> '{etf,inverse}')::boolean, false);

-- Supabase default privileges can grant table verbs before RLS is considered.
-- Keep public market tables explicitly read-only at both the GRANT and RLS layers.

revoke all on
  public.stock_master,
  public.stock_snapshots,
  public.stock_price_history,
  public.stock_monthly_revenues,
  public.stock_quarterly_financials,
  public.stock_institutional_flows,
  public.stock_margin_history,
  public.stock_analysis_cache,
  public.opportunity_score_history,
  public.stock_sync_state
from anon, authenticated;

grant select on
  public.stock_master,
  public.stock_snapshots,
  public.stock_price_history,
  public.stock_monthly_revenues,
  public.stock_quarterly_financials,
  public.stock_institutional_flows,
  public.stock_margin_history,
  public.stock_analysis_cache,
  public.opportunity_score_history,
  public.stock_sync_state
to anon, authenticated;

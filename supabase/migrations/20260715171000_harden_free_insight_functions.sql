-- The v17 insight functions expose aggregates of tables that are already
-- public-read under RLS.  SECURITY INVOKER keeps those same RLS/grant checks
-- in force and avoids an unnecessary public SECURITY DEFINER surface.

alter function public.twss_peer_metric(text, text, text, text, numeric, boolean)
  security invoker;
alter function public.twss_get_stock_context(text)
  security invoker;
alter function public.twss_public_data_health()
  security invoker;

revoke all on function public.twss_peer_metric(text, text, text, text, numeric, boolean)
  from public;
grant execute on function public.twss_peer_metric(text, text, text, text, numeric, boolean)
  to anon, authenticated, service_role;

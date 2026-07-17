-- Expose only the immutable, sanitized v20.1 read models to browser clients.
-- The underlying append-only tables remain private; these SECURITY DEFINER
-- functions are the narrowly-scoped public boundary.

alter function public.twss_v20_read_publication_state()
  security definer;
alter function public.twss_v20_read_publication_state()
  set search_path = '';

alter function public.twss_v20_read_rankings(jsonb)
  security definer;
alter function public.twss_v20_read_rankings(jsonb)
  set search_path = '';

alter function public.twss_v20_read_stock_snapshot(jsonb)
  security definer;
alter function public.twss_v20_read_stock_snapshot(jsonb)
  set search_path = '';

alter function public.twss_v20_read_validation_summary(jsonb)
  security definer;
alter function public.twss_v20_read_validation_summary(jsonb)
  set search_path = '';

revoke all on function public.twss_v20_read_publication_state()
  from public, anon, authenticated, service_role;
revoke all on function public.twss_v20_read_rankings(jsonb)
  from public, anon, authenticated, service_role;
revoke all on function public.twss_v20_read_stock_snapshot(jsonb)
  from public, anon, authenticated, service_role;
revoke all on function public.twss_v20_read_validation_summary(jsonb)
  from public, anon, authenticated, service_role;

grant execute on function public.twss_v20_read_publication_state()
  to anon, authenticated, service_role;
grant execute on function public.twss_v20_read_rankings(jsonb)
  to anon, authenticated, service_role;
grant execute on function public.twss_v20_read_stock_snapshot(jsonb)
  to anon, authenticated, service_role;
grant execute on function public.twss_v20_read_validation_summary(jsonb)
  to anon, authenticated, service_role;

comment on function public.twss_v20_read_publication_state() is
  'Public immutable publication metadata read model. SECURITY DEFINER is intentional; underlying tables stay private.';
comment on function public.twss_v20_read_rankings(jsonb) is
  'Public immutable ranking read model. Returns eligible public_visible items only and rejects the 60-day research horizon.';
comment on function public.twss_v20_read_stock_snapshot(jsonb) is
  'Public immutable stock snapshot read model. Returns public_visible items only; the table contract makes research-only 60-day rows non-public.';
comment on function public.twss_v20_read_validation_summary(jsonb) is
  'Public point-in-time validation read model. Returns eligible public_visible non-research observations only and rejects the 60-day research horizon.';

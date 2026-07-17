-- The Data API authenticator has an eight-second statement timeout. Copying a
-- complete 1,200+ symbol, eight-horizon immutable publication can legitimately
-- exceed that bound, even though the operation is bounded and atomic. Extend
-- only this service-role publication RPC; do not relax the role-wide timeout.

alter function public.twss_v20_publish_recommendation_run(jsonb)
  set statement_timeout = '120s';

comment on function public.twss_v20_publish_recommendation_run(jsonb) is
  'Service-only atomic v20 publisher. Its function-scoped 120-second statement timeout covers the bounded immutable copy without changing the Data API role-wide timeout.';

-- Rollback:
-- alter function public.twss_v20_publish_recommendation_run(jsonb)
--   reset statement_timeout;

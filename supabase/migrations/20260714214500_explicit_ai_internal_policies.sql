-- Internal AI audit/usage tables stay completely hidden from public roles.
-- Explicit service-role policies document the intended access and keep the
-- database advisor from mistaking the deliberate deny-by-default setup for an
-- accidentally unfinished RLS configuration.

drop policy if exists ai_research_runs_service_role_all on public.ai_research_runs;
create policy ai_research_runs_service_role_all on public.ai_research_runs
  for all to service_role using (true) with check (true);

drop policy if exists ai_research_usage_service_role_all on public.ai_research_usage;
create policy ai_research_usage_service_role_all on public.ai_research_usage
  for all to service_role using (true) with check (true);

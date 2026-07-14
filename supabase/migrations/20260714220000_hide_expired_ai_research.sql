-- Expired AI summaries must not remain publicly readable through a direct
-- PostgREST request. The Edge function can still refresh the same input hash
-- through the service role and extend generated_at/expires_at atomically.

drop policy if exists ai_stock_research_public_read on public.ai_stock_research;
create policy ai_stock_research_public_read on public.ai_stock_research
  for select to anon, authenticated
  using (status = 'ready' and (expires_at is null or expires_at > now()));

-- Let the server-only AI_DAILY_LIMIT secret be the single configurable limit.
-- An empty cron body makes the Edge function fall back to that value (default
-- 12, hard maximum 20) instead of silently capping a higher explicit setting.
do $$
declare
  existing_job bigint;
begin
  for existing_job in select jobid from cron.job where jobname = 'twss-ai-research-weekday'
  loop
    perform cron.unschedule(existing_job);
  end loop;
end
$$;

select cron.schedule(
  'twss-ai-research-weekday',
  '20 10 * * 1-5',
  $job$
    select net.http_post(
      url := 'https://lfkdkdyaatdlizryiyon.supabase.co/functions/v1/twss-ai-research',
      headers := jsonb_build_object(
        'Content-Type', 'application/json',
        'x-twss-sync-token', (
          select decrypted_secret from vault.decrypted_secrets where name = 'twss_sync_token'
        )
      ),
      body := '{}'::jsonb,
      timeout_milliseconds := 300000
    );
  $job$
);

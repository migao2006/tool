-- Keep the FinMind credential in Supabase Vault.  The sync Edge Function uses
-- its built-in service role to resolve it; browser roles cannot call this RPC.

create or replace function public.twss_finmind_token()
returns text
language sql
stable
security definer
set search_path = ''
as $$
  select s.decrypted_secret
  from vault.decrypted_secrets s
  where s.name = 'finmind_api_token'
  order by s.created_at desc
  limit 1;
$$;

revoke all on function public.twss_finmind_token()
  from public, anon, authenticated;
grant execute on function public.twss_finmind_token()
  to service_role;

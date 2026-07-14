-- Server-only fallback for deployments that cannot manage Edge Function
-- secrets through automation. The plaintext value is stored separately in
-- Supabase Vault and never appears in this migration or the source archive.

create or replace function public.twss_get_gemini_api_key()
returns text
language sql
stable
security invoker
set search_path = ''
as $$
  select decrypted_secret
  from vault.decrypted_secrets
  where name = 'twss_gemini_api_key'
  limit 1;
$$;

revoke all on function public.twss_get_gemini_api_key() from public, anon, authenticated;
grant execute on function public.twss_get_gemini_api_key() to service_role;

comment on function public.twss_get_gemini_api_key() is
  'Service-role-only Vault fallback for the independent Gemini research Edge Function.';

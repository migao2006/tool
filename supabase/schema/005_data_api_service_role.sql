begin;

-- Register the research schema with PostgREST while keeping browser roles blocked.
alter role authenticator
  set pgrst.db_schemas = 'public, graphql_public, market_data';

revoke all on schema market_data from public, anon, authenticated;
revoke all on all tables in schema market_data from public, anon, authenticated;
revoke all on all sequences in schema market_data from public, anon, authenticated;

grant usage on schema market_data to service_role;
grant select, insert, update, delete on all tables in schema market_data to service_role;
grant usage, select on all sequences in schema market_data to service_role;

commit;

notify pgrst, 'reload config';
notify pgrst, 'reload schema';

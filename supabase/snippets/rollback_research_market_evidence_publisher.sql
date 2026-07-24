begin;

revoke all on function market_data.publish_research_prediction_snapshot(
  jsonb,
  jsonb,
  jsonb
) from public, anon, authenticated, service_role;

drop function market_data.publish_research_prediction_snapshot(
  jsonb,
  jsonb,
  jsonb
);

commit;

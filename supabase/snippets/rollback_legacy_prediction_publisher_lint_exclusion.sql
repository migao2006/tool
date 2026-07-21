begin;

set local lock_timeout = '5s';
set local statement_timeout = '60s';

alter function
market_data.publish_research_prediction_snapshot_twse_v1(jsonb, jsonb)
reset "plpgsql_check.mode";

commit;

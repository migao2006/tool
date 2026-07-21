begin;

set local lock_timeout = '5s';
set local statement_timeout = '60s';

revoke all on function market_data.consume_prediction_snapshot_rate_limit(
  text,
  integer,
  integer
) from public, anon, authenticated, service_role;
drop function market_data.consume_prediction_snapshot_rate_limit(
  text,
  integer,
  integer
);
drop table market_data.prediction_snapshot_rate_limits;

commit;

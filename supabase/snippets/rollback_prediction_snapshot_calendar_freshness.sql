begin;

revoke all on function market_data.get_prediction_snapshot_rows_v2(
  integer,
  text,
  timestamptz
) from public, anon, authenticated, service_role;

drop function if exists market_data.get_prediction_snapshot_rows_v2(
  integer,
  text,
  timestamptz
);

drop index if exists market_data.trading_calendar_observations_freshness_idx;

commit;

notify pgrst, 'reload schema';

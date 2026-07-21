begin;

revoke all on function market_data.get_prediction_snapshot_rows(integer, text, timestamptz)
from public, anon, authenticated, service_role;

drop function if exists market_data.get_prediction_snapshot_rows(integer, text, timestamptz);

drop index if exists market_data.validation_runs_snapshot_lookup_idx;

commit;

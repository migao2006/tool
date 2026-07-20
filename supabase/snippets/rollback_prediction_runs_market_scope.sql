begin;

set local search_path = pg_catalog, public, extensions;
set local lock_timeout = '5s';
set local statement_timeout = '60s';

do $guard$
begin
  if exists (
    select 1
    from market_data.prediction_runs
    where market_scope = 'TPEX'
  ) then
    raise exception using
      errcode = '55000',
      message = 'rollback blocked: TPEX prediction runs exist';
  end if;
end
$guard$;

drop function market_data.publish_research_prediction_snapshot(jsonb, jsonb);
alter function
market_data.publish_research_prediction_snapshot_twse_v1(jsonb, jsonb)
rename to publish_research_prediction_snapshot;

revoke all on function market_data.publish_research_prediction_snapshot(
    jsonb,
    jsonb
)
from public, anon, authenticated;
grant execute on function market_data.publish_research_prediction_snapshot(
    jsonb,
    jsonb
)
to service_role;

drop trigger if exists stock_predictions_market_scope_guard
on market_data.stock_predictions;
drop trigger if exists market_predictions_market_scope_guard
on market_data.market_predictions;
drop trigger if exists prediction_runs_market_scope_immutable_guard
on market_data.prediction_runs;

drop function market_data.enforce_prediction_child_market_scope();
drop function market_data.enforce_prediction_run_market_scope_immutable();

-- A transaction-scoped rollback cannot drop an index concurrently.
-- noqa: disable=PG01
drop index if exists market_data.prediction_runs_market_stale_lookup_idx;
-- noqa: enable=PG01

alter table market_data.prediction_runs
drop constraint prediction_runs_market_identity_key;
alter table market_data.prediction_runs
add constraint
prediction_runs_decision_at_horizon_model_bundle_version_key unique (
    decision_at,
    horizon,
    model_bundle_version
);

alter table market_data.prediction_runs
drop constraint prediction_runs_market_scope_check;
alter table market_data.prediction_runs
drop column market_scope;

commit;

notify pgrst, 'reload schema';

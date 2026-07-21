begin;

-- Override schema-wide default privileges for internal control tables.
revoke all on table public.home_data_status from service_role;
grant select, insert, update on table public.home_data_status to service_role;

revoke all on table market_data.historical_backfill_tasks from service_role;
grant select, insert, update
on table market_data.historical_backfill_tasks to service_role;
revoke all on sequence market_data.historical_backfill_tasks_task_id_seq
from service_role;
grant usage, select
on sequence market_data.historical_backfill_tasks_task_id_seq to service_role;

revoke all on table market_data.historical_archive_objects from service_role;
grant select, insert, update
on table market_data.historical_archive_objects to service_role;
revoke all on sequence market_data.historical_archive_objects_archive_id_seq
from service_role;
grant usage, select
on sequence market_data.historical_archive_objects_archive_id_seq
to service_role;

revoke all on table market_data.security_listing_periods from service_role;
grant select, insert
on table market_data.security_listing_periods to service_role;
revoke all on sequence
market_data.security_listing_periods_listing_evidence_id_seq
from service_role;
grant usage, select on sequence
market_data.security_listing_periods_listing_evidence_id_seq
to service_role;

revoke all on table market_data.trading_calendar_observations
from service_role;
grant select, insert on table market_data.trading_calendar_observations
to service_role;
revoke all on sequence
market_data.trading_calendar_observations_calendar_observation_id_seq
from service_role;
grant usage, select on sequence
market_data.trading_calendar_observations_calendar_observation_id_seq
to service_role;

commit;

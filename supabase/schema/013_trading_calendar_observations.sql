begin;

set local search_path = pg_catalog, public, extensions;

create table if not exists market_data.trading_calendar_observations (
    calendar_observation_id bigint generated always as identity primary key,
    market text not null,
    trading_date date not null,
    is_trading_day boolean not null,
    opens_at timestamptz,
    closes_at timestamptz,
    decision_data_cutoff_at timestamptz,
    market_basis text not null,
    calendar_verification_status text not null,
    source_id bigint not null
    references market_data.data_sources (source_id) on delete restrict,
    source_dataset text not null,
    source_event_id text not null,
    source_version text not null,
    source_revision_hash text not null,
    source_payload_hash text not null,
    source_url text not null,
    source_row jsonb not null,
    first_observed_at timestamptz not null,
    available_at timestamptz not null,
    available_at_basis text not null,
    usage_scope text not null,
    system_status text not null,
    reason_codes text [] not null default '{}'::text [],
    ingested_at timestamptz not null default statement_timestamp(),
    constraint trading_calendar_observations_session_check check (
        market in ('TWSE', 'TPEX')
        and calendar_verification_status in (
            'VERIFIED', 'UNRESOLVED', 'CONFLICT'
        )
        and market_basis in ('SOURCE_ASSERTED', 'SCHEDULING_HINT')
        and (
            (
                is_trading_day
                and opens_at is not null
                and closes_at is not null
                and decision_data_cutoff_at is not null
                and opens_at < closes_at
                and closes_at <= decision_data_cutoff_at
                and timezone('Asia/Taipei', opens_at)::date = trading_date
                and timezone('Asia/Taipei', closes_at)::date = trading_date
                and timezone(
                    'Asia/Taipei', decision_data_cutoff_at
                )::date = trading_date
            )
            or (
                not is_trading_day
                and opens_at is null
                and closes_at is null
                and decision_data_cutoff_at is null
            )
        )
    ),
    constraint trading_calendar_observations_lineage_check check (
        nullif(btrim(source_dataset), '') is not null
        and nullif(btrim(source_event_id), '') is not null
        and nullif(btrim(source_version), '') is not null
        and source_revision_hash ~ '^[0-9a-f]{64}$'
        and source_payload_hash ~ '^[0-9a-f]{64}$'
        and source_url ~ '^https://'
        and jsonb_typeof(source_row) = 'object'
        and first_observed_at <= ingested_at
        and available_at_basis in (
            'OFFICIAL_PUBLICATION_AT',
            'VERSIONED_SNAPSHOT',
            'FIRST_OBSERVED_AT_RETRIEVAL'
        )
        and (
            (
                available_at_basis = 'OFFICIAL_PUBLICATION_AT'
                and available_at <= first_observed_at
            )
            or (
                available_at_basis in (
                    'VERSIONED_SNAPSHOT',
                    'FIRST_OBSERVED_AT_RETRIEVAL'
                )
                and available_at = first_observed_at
            )
        )
    ),
    constraint trading_calendar_observations_status_check check (
        array_position(reason_codes, null) is null
        and (
            (
                calendar_verification_status = 'VERIFIED'
                and market_basis = 'SOURCE_ASSERTED'
                and available_at_basis in (
                    'OFFICIAL_PUBLICATION_AT',
                    'VERSIONED_SNAPSHOT'
                )
                and usage_scope = 'POINT_IN_TIME_CALENDAR'
                and system_status = 'PASS'
                and cardinality(reason_codes) = 0
                and available_at <= decision_data_cutoff_at
            )
            or (
                calendar_verification_status in ('UNRESOLVED', 'CONFLICT')
                and usage_scope = 'CALENDAR_RESEARCH_ONLY'
                and system_status in ('RESEARCH_ONLY', 'FAIL')
                and cardinality(reason_codes) > 0
            )
        )
    )
);

-- noqa: disable=PG01
create unique index if not exists trading_calendar_observations_revision_uidx
on market_data.trading_calendar_observations (
    source_id,
    source_dataset,
    source_event_id,
    market,
    trading_date,
    source_revision_hash
);

create unique index if not exists
trading_calendar_observations_verified_date_uidx
on market_data.trading_calendar_observations (market, trading_date)
where calendar_verification_status = 'VERIFIED';

create index if not exists trading_calendar_observations_lookup_idx
on market_data.trading_calendar_observations (
    market,
    trading_date,
    available_at desc
);

create index if not exists trading_calendar_observations_source_idx
on market_data.trading_calendar_observations (source_id);
-- noqa: enable=PG01

comment on table market_data.trading_calendar_observations is
'Append-only versioned trading-calendar evidence. Revisions are inserted;
contradictory evidence is CONFLICT and never overwrites an earlier row.';
comment on column market_data.trading_calendar_observations.market_basis is
'SCHEDULING_HINT is never sufficient for VERIFIED point-in-time calendar use.';
comment on column market_data.trading_calendar_observations.available_at is
'VERSIONED_SNAPSHOT becomes eligible at first_observed_at, never before it.';

drop trigger if exists trading_calendar_observations_append_only
on market_data.trading_calendar_observations;
create trigger trading_calendar_observations_append_only
before update or delete on market_data.trading_calendar_observations
for each row execute function market_data.reject_pit_contract_mutation();

alter table market_data.trading_calendar_observations enable row level security;
alter table market_data.trading_calendar_observations force row level security;

revoke all on market_data.trading_calendar_observations
from public, anon, authenticated, service_role;
revoke all on sequence
market_data.trading_calendar_observations_calendar_observation_id_seq
from public, anon, authenticated, service_role;

grant select,
insert on market_data.trading_calendar_observations to service_role;
grant usage, select
on sequence
market_data.trading_calendar_observations_calendar_observation_id_seq
to service_role;

commit;

notify pgrst, 'reload schema';

begin;

set local search_path = pg_catalog, public, extensions;

create table if not exists
market_data.historical_corporate_action_observations (
    observation_id bigint generated always as identity primary key,
    action_event_id text not null,
    listing_evidence_id bigint
    references market_data.security_listing_periods (
        listing_evidence_id
    ) on delete restrict,
    listing_period_id text,
    security_id bigint
    references market_data.securities (security_id) on delete restrict,
    market text not null,
    asset_type text not null,
    source_symbol text not null,
    action_type text not null,
    action_status text not null,
    ex_date date not null,
    payable_date date,
    announced_at timestamptz,
    cash_amount_per_share numeric(20, 8),
    share_ratio numeric(20, 10),
    share_multiplier numeric(20, 10),
    subscription_price_per_share numeric(20, 8),
    reference_price_adjustment numeric(20, 8),
    source_row_complete boolean not null,
    identity_resolution_status text not null,
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
    constraint historical_company_action_identity_check check (
        market in ('TWSE', 'TPEX')
        and asset_type in ('COMMON_STOCK', 'ETF')
        and nullif(btrim(action_event_id), '') is not null
        and length(action_event_id) <= 256
        and nullif(btrim(source_symbol), '') is not null
        and length(source_symbol) <= 32
        and action_type in (
            'CASH_DIVIDEND',
            'STOCK_DIVIDEND',
            'SPLIT',
            'CAPITAL_REDUCTION',
            'RIGHTS',
            'OTHER'
        )
        and action_status in ('ANNOUNCED', 'REALIZED', 'CANCELLED')
        and identity_resolution_status in ('VERIFIED', 'UNRESOLVED', 'CONFLICT')
        and (
            (
                identity_resolution_status = 'VERIFIED'
                and listing_evidence_id is not null
                and listing_period_id is not null
                and security_id is not null
            )
            or (
                identity_resolution_status in ('UNRESOLVED', 'CONFLICT')
                and listing_evidence_id is null
                and listing_period_id is null
                and security_id is null
            )
        )
    ),
    constraint historical_company_action_terms_check check (
        (payable_date is null or payable_date >= ex_date)
        and (announced_at is null or announced_at <= available_at)
        and (
            cash_amount_per_share is null
            or cash_amount_per_share >= 0
        )
        and (share_ratio is null or share_ratio >= 0)
        and (share_multiplier is null or share_multiplier > 0)
        and (
            subscription_price_per_share is null
            or subscription_price_per_share >= 0
        )
        and (
            reference_price_adjustment is null
            or reference_price_adjustment >= 0
        )
        and (
            action_status <> 'REALIZED'
            or ex_date <= timezone('Asia/Taipei', available_at)::date
        )
        and (
            action_status <> 'REALIZED'
            or not source_row_complete
            or action_type = 'OTHER'
            or (
                action_type = 'CASH_DIVIDEND'
                and cash_amount_per_share > 0
            )
            or (
                action_type = 'STOCK_DIVIDEND'
                and share_ratio > 0
                and share_multiplier = 1 + share_ratio
            )
            or (
                action_type = 'SPLIT'
                and share_multiplier > 0
                and share_multiplier <> 1
            )
            or (
                action_type = 'CAPITAL_REDUCTION'
                and (
                    (share_multiplier > 0 and share_multiplier < 1)
                    or cash_amount_per_share > 0
                    or reference_price_adjustment > 0
                )
            )
            or (
                action_type = 'RIGHTS'
                and share_ratio > 0
                and subscription_price_per_share is not null
            )
        )
    ),
    constraint historical_company_action_lineage_check check (
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
    constraint historical_company_action_status_check check (
        array_position(reason_codes, null) is null
        and (
            (
                identity_resolution_status = 'VERIFIED'
                and source_row_complete
                and available_at_basis in (
                    'OFFICIAL_PUBLICATION_AT',
                    'VERSIONED_SNAPSHOT'
                )
                and action_type <> 'OTHER'
                and usage_scope = 'POINT_IN_TIME_ACTION_LIFECYCLE'
                and system_status = 'PASS'
                and cardinality(reason_codes) = 0
            )
            or (
                usage_scope = 'ACTION_RESEARCH_ONLY'
                and system_status in ('RESEARCH_ONLY', 'FAIL')
                and cardinality(reason_codes) > 0
                and (
                    identity_resolution_status in ('UNRESOLVED', 'CONFLICT')
                    or not source_row_complete
                    or available_at_basis = 'FIRST_OBSERVED_AT_RETRIEVAL'
                    or action_type = 'OTHER'
                )
            )
        )
    )
);

create table if not exists
market_data.company_action_coverage_observations (
    observation_id bigint generated always as identity primary key,
    coverage_key text not null,
    listing_evidence_id bigint
    references market_data.security_listing_periods (
        listing_evidence_id
    ) on delete restrict,
    listing_period_id text,
    security_id bigint
    references market_data.securities (security_id) on delete restrict,
    market text not null,
    asset_type text not null,
    source_symbol text not null,
    coverage_start_date date not null,
    coverage_end_date date not null,
    covered_action_types text [] not null,
    coverage_completeness text not null,
    coverage_result text not null,
    observed_event_count integer not null,
    unsupported_event_count integer not null,
    unresolved_event_count integer not null,
    normalized_event_set_sha256 text not null,
    source_row_complete boolean not null,
    coverage_resolution_status text not null,
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
    constraint company_action_coverage_identity_check check (
        coverage_key ~ '^[0-9a-f]{64}$'
        and market in ('TWSE', 'TPEX')
        and asset_type in ('COMMON_STOCK', 'ETF')
        and nullif(btrim(source_symbol), '') is not null
        and length(source_symbol) <= 32
        and coverage_start_date <= coverage_end_date
        and coverage_resolution_status in ('VERIFIED', 'UNRESOLVED', 'CONFLICT')
        and (
            (
                coverage_resolution_status = 'VERIFIED'
                and listing_evidence_id is not null
                and listing_period_id is not null
                and security_id is not null
            )
            or (
                coverage_resolution_status in ('UNRESOLVED', 'CONFLICT')
                and listing_evidence_id is null
                and listing_period_id is null
                and security_id is null
            )
        )
    ),
    constraint company_action_coverage_scope_check check (
        cardinality(covered_action_types) > 0
        and array_position(covered_action_types, null) is null
        and covered_action_types <@ array[
            'CASH_DIVIDEND',
            'STOCK_DIVIDEND',
            'SPLIT',
            'CAPITAL_REDUCTION',
            'RIGHTS',
            'OTHER'
        ]::text []
        and coverage_completeness in ('COMPLETE', 'PARTIAL', 'UNKNOWN')
        and coverage_result in ('EVENTS_PRESENT', 'NO_EVENTS', 'UNKNOWN')
        and observed_event_count >= 0
        and unsupported_event_count >= 0
        and unresolved_event_count >= 0
        and unsupported_event_count + unresolved_event_count
            <= observed_event_count
        and (
            (coverage_result = 'EVENTS_PRESENT' and observed_event_count > 0)
            or (coverage_result = 'NO_EVENTS' and observed_event_count = 0)
            or coverage_result = 'UNKNOWN'
        )
    ),
    constraint company_action_coverage_lineage_check check (
        nullif(btrim(source_dataset), '') is not null
        and nullif(btrim(source_event_id), '') is not null
        and nullif(btrim(source_version), '') is not null
        and source_revision_hash ~ '^[0-9a-f]{64}$'
        and source_payload_hash ~ '^[0-9a-f]{64}$'
        and normalized_event_set_sha256 ~ '^[0-9a-f]{64}$'
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
    constraint company_action_coverage_status_check check (
        array_position(reason_codes, null) is null
        and (
            (
                coverage_resolution_status = 'VERIFIED'
                and coverage_completeness = 'COMPLETE'
                and coverage_result in ('EVENTS_PRESENT', 'NO_EVENTS')
                and source_row_complete
                and covered_action_types @> array[
                    'CASH_DIVIDEND',
                    'STOCK_DIVIDEND',
                    'SPLIT',
                    'CAPITAL_REDUCTION',
                    'RIGHTS',
                    'OTHER'
                ]::text []
                and available_at_basis in (
                    'OFFICIAL_PUBLICATION_AT',
                    'VERSIONED_SNAPSHOT'
                )
                and coverage_end_date <= timezone(
                    'Asia/Taipei', available_at
                )::date
                and unsupported_event_count = 0
                and unresolved_event_count = 0
                and usage_scope = 'POINT_IN_TIME_ACTION_COVERAGE'
                and system_status = 'PASS'
                and cardinality(reason_codes) = 0
            )
            or (
                usage_scope = 'ACTION_COVERAGE_RESEARCH_ONLY'
                and system_status in ('RESEARCH_ONLY', 'FAIL')
                and cardinality(reason_codes) > 0
                and (
                    coverage_resolution_status in ('UNRESOLVED', 'CONFLICT')
                    or coverage_completeness <> 'COMPLETE'
                    or coverage_result = 'UNKNOWN'
                    or not source_row_complete
                    or not (
                        covered_action_types @> array[
                            'CASH_DIVIDEND',
                            'STOCK_DIVIDEND',
                            'SPLIT',
                            'CAPITAL_REDUCTION',
                            'RIGHTS',
                            'OTHER'
                        ]::text []
                    )
                    or available_at_basis = 'FIRST_OBSERVED_AT_RETRIEVAL'
                    or coverage_end_date > timezone(
                        'Asia/Taipei', available_at
                    )::date
                    or unsupported_event_count > 0
                    or unresolved_event_count > 0
                )
            )
        )
    )
);

-- noqa: disable=PG01
create unique index if not exists
historical_company_action_observations_revision_uidx
on market_data.historical_corporate_action_observations (
    source_id,
    source_dataset,
    source_event_id,
    action_type,
    source_revision_hash
);

create index if not exists historical_company_action_lookup_idx
on market_data.historical_corporate_action_observations (
    listing_period_id,
    ex_date,
    action_status,
    available_at desc
);

create index if not exists historical_company_action_listing_evidence_idx
on market_data.historical_corporate_action_observations (
    listing_evidence_id
);

create index if not exists historical_company_action_security_idx
on market_data.historical_corporate_action_observations (security_id);

create index if not exists historical_company_action_realized_idx
on market_data.historical_corporate_action_observations (
    security_id,
    ex_date,
    available_at desc
)
where action_status = 'REALIZED'
and identity_resolution_status = 'VERIFIED'
and source_row_complete
and system_status = 'PASS';

create unique index if not exists company_action_coverage_revision_uidx
on market_data.company_action_coverage_observations (
    source_id,
    source_dataset,
    source_event_id,
    coverage_key,
    source_revision_hash
);

create index if not exists company_action_coverage_listing_evidence_idx
on market_data.company_action_coverage_observations (listing_evidence_id);

create index if not exists company_action_coverage_security_idx
on market_data.company_action_coverage_observations (security_id);

create index if not exists company_action_coverage_lookup_idx
on market_data.company_action_coverage_observations (
    listing_period_id,
    coverage_start_date,
    coverage_end_date,
    available_at desc
)
where coverage_resolution_status = 'VERIFIED';
-- noqa: enable=PG01

comment on table
market_data.historical_corporate_action_observations is
'Append-only historical action lifecycle evidence. ANNOUNCED, REALIZED and
CANCELLED are separate observations; only complete REALIZED PASS rows may
later contribute executable-return cash flows.';
comment on column
market_data.historical_corporate_action_observations.source_row_complete is
'True only when the source exposes every term required for this lifecycle
observation. It does not make ANNOUNCED or CANCELLED rows label-eligible.';
comment on table market_data.company_action_coverage_observations is
'Append-only evidence that one listing period and date interval was checked
for every corporate-action type, including explicit COMPLETE NO_EVENTS rows.';
comment on column
market_data.company_action_coverage_observations.available_at is
'Earliest evidenced availability. Consumers must additionally require this
timestamp not to exceed their own decision or training-data cutoff.';

create or replace function
market_data.validate_historical_company_action_identity()
returns trigger
language plpgsql
security invoker
set search_path = pg_catalog
as $function$
begin
  if new.identity_resolution_status = 'VERIFIED'
     and not exists (
       select 1
       from market_data.security_listing_periods as listing
       where listing.listing_evidence_id = new.listing_evidence_id
         and listing.listing_period_id = new.listing_period_id
         and listing.security_id = new.security_id
         and listing.listing_market = new.market
         and listing.asset_type = new.asset_type
         and listing.source_symbol = new.source_symbol
         and listing.identity_resolution_status = 'VERIFIED'
         and listing.usage_scope = 'POINT_IN_TIME_IDENTITY'
         and listing.system_status = 'PASS'
         and listing.available_at <= new.available_at
         and listing.effective_from <= new.ex_date
         and (
           listing.effective_to is null
           or new.ex_date < listing.effective_to
         )
     ) then
    raise exception using
      errcode = '23514',
      message = 'VERIFIED historical action conflicts with listing evidence';
  end if;
  return new;
end
$function$;

create or replace function
market_data.validate_company_action_coverage_identity()
returns trigger
language plpgsql
security invoker
set search_path = pg_catalog
as $function$
begin
  if new.coverage_resolution_status = 'VERIFIED'
     and not exists (
       select 1
       from market_data.security_listing_periods as listing
       where listing.listing_evidence_id = new.listing_evidence_id
         and listing.listing_period_id = new.listing_period_id
         and listing.security_id = new.security_id
         and listing.listing_market = new.market
         and listing.asset_type = new.asset_type
         and listing.source_symbol = new.source_symbol
         and listing.identity_resolution_status = 'VERIFIED'
         and listing.usage_scope = 'POINT_IN_TIME_IDENTITY'
         and listing.system_status = 'PASS'
         and listing.available_at <= new.available_at
         and listing.effective_from <= new.coverage_start_date
         and (
           listing.effective_to is null
           or new.coverage_end_date < listing.effective_to
         )
     ) then
    raise exception using
      errcode = '23514',
      message = 'VERIFIED action coverage conflicts with listing evidence';
  end if;
  return new;
end
$function$;

drop trigger if exists historical_company_action_validate_identity
on market_data.historical_corporate_action_observations;
create trigger historical_company_action_validate_identity
before insert on market_data.historical_corporate_action_observations
for each row execute function
market_data.validate_historical_company_action_identity();

drop trigger if exists company_action_coverage_validate_identity
on market_data.company_action_coverage_observations;
create trigger company_action_coverage_validate_identity
before insert on market_data.company_action_coverage_observations
for each row execute function
market_data.validate_company_action_coverage_identity();

drop trigger if exists historical_company_action_append_only
on market_data.historical_corporate_action_observations;
create trigger historical_company_action_append_only
before update or delete
on market_data.historical_corporate_action_observations
for each row execute function market_data.reject_pit_contract_mutation();

drop trigger if exists company_action_coverage_append_only
on market_data.company_action_coverage_observations;
create trigger company_action_coverage_append_only
before update or delete on market_data.company_action_coverage_observations
for each row execute function market_data.reject_pit_contract_mutation();

alter table market_data.historical_corporate_action_observations
enable row level security;
alter table market_data.historical_corporate_action_observations
force row level security;
alter table market_data.company_action_coverage_observations
enable row level security;
alter table market_data.company_action_coverage_observations
force row level security;

revoke all on market_data.historical_corporate_action_observations
from public, anon, authenticated, service_role;
revoke all on sequence
market_data.historical_corporate_action_observations_observation_id_seq
from public, anon, authenticated, service_role;
revoke all on market_data.company_action_coverage_observations
from public, anon, authenticated, service_role;
revoke all on sequence
market_data.company_action_coverage_observations_observation_id_seq
from public, anon, authenticated, service_role;
revoke all on function
market_data.validate_historical_company_action_identity()
from public, anon, authenticated, service_role;
revoke all on function
market_data.validate_company_action_coverage_identity()
from public, anon, authenticated, service_role;

grant select, insert
on market_data.historical_corporate_action_observations to service_role;
grant usage, select on sequence
market_data.historical_corporate_action_observations_observation_id_seq
to service_role;
grant select, insert
on market_data.company_action_coverage_observations to service_role;
grant usage, select on sequence
market_data.company_action_coverage_observations_observation_id_seq
to service_role;

commit;

notify pgrst, 'reload schema';

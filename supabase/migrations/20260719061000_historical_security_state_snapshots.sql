begin;

set local search_path = pg_catalog, public, extensions;

create table if not exists market_data.security_state_snapshots (
    security_state_snapshot_id bigint generated always as identity primary key,
    snapshot_key text not null unique,
    storage_provider text not null,
    bucket_name text not null,
    object_key text not null,
    object_etag text,
    schema_version text not null,
    parquet_sha256 text not null,
    normalized_content_sha256 text not null,
    byte_size bigint not null,
    row_count integer not null,
    fully_observed_row_count integer not null,
    unknown_state_row_count integer not null,
    market text not null,
    asset_type text not null,
    coverage_start_date date not null,
    coverage_end_date date not null,
    state_field_set text [] not null,
    source_id bigint not null
    references market_data.data_sources (source_id) on delete restrict,
    provider_code text not null,
    source_dataset text not null,
    source_event_id text not null,
    source_version text not null,
    source_revision_hash text not null,
    source_payload_hash text not null,
    source_url text not null,
    source_metadata jsonb not null default '{}'::jsonb,
    published_at timestamptz,
    first_observed_at timestamptz not null,
    available_at timestamptz not null,
    available_at_basis text not null,
    verification_status text not null,
    usage_scope text not null,
    system_status text not null,
    reason_codes text [] not null default '{}'::text [],
    git_commit text,
    library_versions jsonb not null default '{}'::jsonb,
    ingested_at timestamptz not null default statement_timestamp(),
    constraint security_state_snapshot_location_uidx
    unique (bucket_name, object_key),
    constraint security_state_snapshot_identity_check check (
        snapshot_key ~ '^[0-9a-f]{64}$'
        and storage_provider = 'CLOUDFLARE_R2'
        and bucket_name ~ '^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$'
        and nullif(btrim(object_key), '') is not null
        and object_key !~ '(^|/)\.\.?(/|$)'
        and object_key !~ '\\'
        and nullif(btrim(schema_version), '') is not null
        and parquet_sha256 ~ '^[0-9a-f]{64}$'
        and normalized_content_sha256 ~ '^[0-9a-f]{64}$'
        and byte_size > 0
        and row_count > 0
        and fully_observed_row_count >= 0
        and unknown_state_row_count >= 0
        and fully_observed_row_count + unknown_state_row_count = row_count
        and market in ('TWSE', 'TPEX')
        and asset_type in ('COMMON_STOCK', 'ETF')
        and coverage_start_date <= coverage_end_date
    ),
    constraint security_state_snapshot_field_set_check check (
        array_position(state_field_set, null) is null
        and cardinality(state_field_set) > 0
    ),
    constraint security_state_snapshot_lineage_check check (
        nullif(btrim(provider_code), '') is not null
        and nullif(btrim(source_dataset), '') is not null
        and nullif(btrim(source_event_id), '') is not null
        and nullif(btrim(source_version), '') is not null
        and source_revision_hash ~ '^[0-9a-f]{64}$'
        and source_payload_hash ~ '^[0-9a-f]{64}$'
        and source_url ~ '^https://'
        and jsonb_typeof(source_metadata) = 'object'
        and first_observed_at <= ingested_at
        and available_at_basis in (
            'OFFICIAL_PUBLICATION_AT',
            'VERSIONED_SNAPSHOT',
            'FIRST_OBSERVED_AT_RETRIEVAL'
        )
        and (
            (
                available_at_basis = 'OFFICIAL_PUBLICATION_AT'
                and published_at is not null
                and available_at = published_at
                and published_at <= first_observed_at
            )
            or (
                available_at_basis = 'VERSIONED_SNAPSHOT'
                and available_at = first_observed_at
                and (
                    published_at is null
                    or published_at <= first_observed_at
                )
            )
            or (
                available_at_basis = 'FIRST_OBSERVED_AT_RETRIEVAL'
                and published_at is null
                and available_at = first_observed_at
            )
        )
        and (object_etag is null or nullif(btrim(object_etag), '') is not null)
        and (git_commit is null or git_commit ~ '^[0-9a-f]{7,40}$')
        and jsonb_typeof(library_versions) = 'object'
    ),
    constraint security_state_snapshot_status_check check (
        verification_status in ('VERIFIED', 'UNRESOLVED', 'CONFLICT')
        and array_position(reason_codes, null) is null
        and (
            (
                verification_status = 'VERIFIED'
                and available_at_basis in (
                    'OFFICIAL_PUBLICATION_AT',
                    'VERSIONED_SNAPSHOT'
                )
                and fully_observed_row_count = row_count
                and unknown_state_row_count = 0
                and state_field_set @> array[
                    'trading_status',
                    'attention_flag',
                    'disposition_flag',
                    'altered_trading_method_flag',
                    'full_cash_delivery_flag',
                    'periodic_auction_flag',
                    'suspended_flag'
                ]::text []
                and usage_scope = 'POINT_IN_TIME_SECURITY_STATE'
                and system_status = 'PASS'
                and cardinality(reason_codes) = 0
                and coverage_end_date <= timezone(
                    'Asia/Taipei', available_at
                )::date
            )
            or (
                verification_status in ('UNRESOLVED', 'CONFLICT')
                and usage_scope = 'SECURITY_STATE_RESEARCH_ONLY'
                and system_status in ('RESEARCH_ONLY', 'FAIL')
                and cardinality(reason_codes) > 0
            )
        )
    )
);

-- noqa: disable=PG01
create unique index if not exists security_state_snapshots_revision_uidx
on market_data.security_state_snapshots (
    source_id,
    source_dataset,
    source_event_id,
    market,
    asset_type,
    coverage_start_date,
    coverage_end_date,
    source_revision_hash
);

create index if not exists security_state_snapshots_lookup_idx
on market_data.security_state_snapshots (
    market,
    asset_type,
    coverage_start_date,
    coverage_end_date,
    available_at desc
);
-- noqa: enable=PG01

comment on table market_data.security_state_snapshots is
'Append-only metadata for immutable point-in-time security-state Parquet
objects in private Cloudflare R2. Object rows must retain listing_period_id,
security_id and every state field; PostgreSQL stores no duplicate payload.';
comment on column
market_data.security_state_snapshots.unknown_state_row_count is
'Rows with any unknown critical state. Absence from an event list never proves
that a security was ACTIVE or that every restriction flag was false.';
comment on column market_data.security_state_snapshots.available_at is
'Earliest evidenced availability. FIRST_OBSERVED_AT_RETRIEVAL remains
research-only and is never backdated to the coverage date.';

drop trigger if exists security_state_snapshots_append_only
on market_data.security_state_snapshots;
create trigger security_state_snapshots_append_only
before update or delete on market_data.security_state_snapshots
for each row execute function market_data.reject_pit_contract_mutation();

alter table market_data.security_state_snapshots enable row level security;
alter table market_data.security_state_snapshots force row level security;

revoke all on market_data.security_state_snapshots
from public, anon, authenticated, service_role;
revoke all on sequence
market_data.security_state_snapshots_security_state_snapshot_id_seq
from public, anon, authenticated, service_role;

grant select, insert on market_data.security_state_snapshots to service_role;
grant usage, select on sequence
market_data.security_state_snapshots_security_state_snapshot_id_seq
to service_role;

commit;

notify pgrst, 'reload schema';

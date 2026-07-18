begin;

set local search_path = pg_catalog, public, extensions;

create table if not exists market_data.historical_archive_objects (
    archive_id bigint generated always as identity primary key,
    archive_key text not null unique,
    storage_provider text not null,
    bucket_name text not null,
    object_key text not null,
    object_etag text,
    schema_version text not null,
    provider_code text not null,
    source_dataset text not null,
    source_version text not null,
    source_symbol text not null,
    scheduled_market text not null,
    asset_type text not null,
    requested_start_date date not null,
    requested_end_date date not null,
    min_trade_date date not null,
    max_trade_date date not null,
    source_payload_hash text not null,
    parquet_sha256 text not null,
    byte_size bigint not null,
    row_count integer not null,
    parsed_row_count integer not null,
    quarantined_row_count integer not null,
    first_observed_at timestamptz not null,
    point_in_time_status text not null,
    usage_scope text not null,
    system_status text not null,
    reason_codes text [] not null,
    backfill_task_id bigint,
    git_commit text,
    library_versions jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint historical_archive_object_location_uidx
    unique (bucket_name, object_key),
    constraint historical_archive_identity_check check (
        archive_key ~ '^[0-9a-f]{64}$'
        and source_payload_hash ~ '^[0-9a-f]{64}$'
        and parquet_sha256 ~ '^[0-9a-f]{64}$'
        and bucket_name ~ '^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$'
        and nullif(btrim(object_key), '') is not null
        and object_key !~ '(^|/)\.\.?(/|$)'
        and object_key !~ '\\'
    ),
    constraint historical_archive_scope_check check (
        storage_provider = 'CLOUDFLARE_R2'
        and provider_code = 'FINMIND'
        and source_dataset = 'daily_bars'
        and scheduled_market in ('TWSE', 'TPEX')
        and asset_type in ('COMMON_STOCK', 'ETF')
        and requested_start_date <= requested_end_date
        and requested_start_date <= min_trade_date
        and min_trade_date <= max_trade_date
        and max_trade_date <= requested_end_date
        and point_in_time_status = 'UNVERIFIED'
        and usage_scope = 'RAW_LANDING_ONLY'
        and system_status = 'RESEARCH_ONLY'
    ),
    constraint historical_archive_counts_check check (
        byte_size > 0
        and row_count > 0
        and parsed_row_count >= 0
        and quarantined_row_count >= 0
        and parsed_row_count + quarantined_row_count = row_count
        and cardinality(reason_codes) > 0
    ),
    constraint historical_archive_optional_metadata_check check (
        (object_etag is null or nullif(btrim(object_etag), '') is not null)
        and (backfill_task_id is null or backfill_task_id > 0)
        and (git_commit is null or git_commit ~ '^[0-9a-f]{7,40}$')
        and jsonb_typeof(library_versions) = 'object'
    )
);

-- noqa: disable=PG01
create index if not exists historical_archive_objects_symbol_date_idx
on market_data.historical_archive_objects (
    scheduled_market,
    asset_type,
    source_symbol,
    requested_start_date,
    requested_end_date
);

create index if not exists historical_archive_objects_observed_at_idx
on market_data.historical_archive_objects (first_observed_at);

create index if not exists historical_archive_objects_payload_hash_idx
on market_data.historical_archive_objects (
    provider_code,
    source_dataset,
    source_payload_hash
);
-- noqa: enable=PG01

comment on table market_data.historical_archive_objects is
'Private manifest for research-only Parquet objects in Cloudflare R2.';
comment on column market_data.historical_archive_objects.scheduled_market is
'Queue market; not verified historical point-in-time identity evidence.';
comment on column market_data.historical_archive_objects.first_observed_at is
'Project retrieval time, not the exchange publication time.';

alter table market_data.historical_archive_objects enable row level security;

revoke all on market_data.historical_archive_objects
from public, anon, authenticated;
revoke all on sequence market_data.historical_archive_objects_archive_id_seq
from public, anon, authenticated;

grant select, insert, update
on market_data.historical_archive_objects to service_role;
grant usage, select
on sequence market_data.historical_archive_objects_archive_id_seq
to service_role;

commit;

notify pgrst, 'reload schema';

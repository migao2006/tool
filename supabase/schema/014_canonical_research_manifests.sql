begin;

set local search_path = pg_catalog, public, extensions;

create table if not exists market_data.daily_bar_publication_snapshots (
    publication_snapshot_id bigint generated always as identity primary key,
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
    market text not null,
    asset_type text not null,
    trading_date date not null,
    provider_code text not null,
    source_id bigint not null
    references market_data.data_sources (source_id) on delete restrict,
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
    constraint daily_bar_publication_snapshot_location_uidx
    unique (bucket_name, object_key),
    constraint daily_bar_publication_snapshot_identity_check check (
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
        and market in ('TWSE', 'TPEX')
        and asset_type in ('COMMON_STOCK', 'ETF')
        and provider_code = market
    ),
    constraint daily_bar_publication_snapshot_lineage_check check (
        nullif(btrim(source_dataset), '') is not null
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
    constraint daily_bar_publication_snapshot_status_check check (
        verification_status in ('VERIFIED', 'UNRESOLVED', 'CONFLICT')
        and array_position(reason_codes, null) is null
        and (
            (
                verification_status = 'VERIFIED'
                and available_at_basis in (
                    'OFFICIAL_PUBLICATION_AT',
                    'VERSIONED_SNAPSHOT'
                )
                and usage_scope = 'POINT_IN_TIME_DAILY_BAR'
                and system_status = 'PASS'
                and cardinality(reason_codes) = 0
                and trading_date <= timezone(
                    'Asia/Taipei', available_at
                )::date
            )
            or (
                verification_status in ('UNRESOLVED', 'CONFLICT')
                and usage_scope = 'BAR_PUBLICATION_RESEARCH_ONLY'
                and system_status in ('RESEARCH_ONLY', 'FAIL')
                and cardinality(reason_codes) > 0
            )
        )
    )
);

-- noqa: disable=PG01
create unique index if not exists
daily_bar_publication_snapshots_revision_uidx
on market_data.daily_bar_publication_snapshots (
    source_id,
    source_dataset,
    source_event_id,
    market,
    asset_type,
    trading_date,
    source_revision_hash
);

create index if not exists daily_bar_publication_snapshots_lookup_idx
on market_data.daily_bar_publication_snapshots (
    market,
    asset_type,
    trading_date,
    available_at desc
);
-- noqa: enable=PG01

comment on table market_data.daily_bar_publication_snapshots is
'Append-only metadata for official or versioned daily-bar evidence stored as
immutable Parquet objects in private Cloudflare R2. No market rows are copied
into PostgreSQL.';
comment on column market_data.daily_bar_publication_snapshots.available_at is
'Earliest evidenced availability. FIRST_OBSERVED_AT_RETRIEVAL is always
research-only and must never be backdated to the trading date.';
comment on column
market_data.daily_bar_publication_snapshots.normalized_content_sha256 is
'Digest of the normalized row collection used to bind later canonical rows to
the exact evidence payload.';

drop trigger if exists daily_bar_publication_snapshots_append_only
on market_data.daily_bar_publication_snapshots;
create trigger daily_bar_publication_snapshots_append_only
before update or delete on market_data.daily_bar_publication_snapshots
for each row execute function market_data.reject_pit_contract_mutation();

alter table market_data.daily_bar_publication_snapshots
enable row level security;
alter table market_data.daily_bar_publication_snapshots
force row level security;

revoke all on market_data.daily_bar_publication_snapshots
from public, anon, authenticated, service_role;
revoke all on sequence
market_data.daily_bar_publication_snapshots_publication_snapshot_id_seq
from public, anon, authenticated, service_role;

grant select, insert on market_data.daily_bar_publication_snapshots
to service_role;
grant usage, select on sequence
market_data.daily_bar_publication_snapshots_publication_snapshot_id_seq
to service_role;

create table if not exists market_data.canonical_dataset_objects (
    canonical_object_id bigint generated always as identity primary key,
    canonical_object_key text not null unique,
    storage_provider text not null,
    bucket_name text not null,
    object_key text not null,
    object_etag text,
    schema_version text not null,
    parquet_sha256 text not null,
    canonical_content_sha256 text not null,
    byte_size bigint not null,
    source_row_count integer not null,
    canonical_row_count integer not null,
    rejected_row_count integer not null,
    quarantined_row_count integer not null,
    research_only_row_count integer not null,
    model_eligible_row_count integer not null,
    market text not null,
    asset_type text not null,
    horizon smallint not null,
    min_trade_date date not null,
    max_trade_date date not null,
    raw_archive_key text not null
    references market_data.historical_archive_objects (archive_key)
    on delete restrict,
    raw_parquet_sha256 text not null,
    raw_manifest_snapshot_sha256 text not null,
    build_input_snapshot_sha256 text not null,
    identity_snapshot_sha256 text,
    calendar_snapshot_sha256 text,
    publication_snapshot_id bigint
    references market_data.daily_bar_publication_snapshots (
        publication_snapshot_id
    ) on delete restrict,
    security_state_snapshot_sha256 text,
    company_action_snapshot_sha256 text,
    builder_version text not null,
    publication_rule_version text not null,
    point_in_time_status text not null,
    usage_scope text not null,
    system_status text not null,
    reason_codes text [] not null,
    reason_counts jsonb not null,
    git_commit text not null,
    library_versions jsonb not null,
    built_at timestamptz not null,
    ingested_at timestamptz not null default statement_timestamp(),
    constraint canonical_dataset_object_location_uidx
    unique (bucket_name, object_key),
    constraint canonical_dataset_object_identity_check check (
        canonical_object_key ~ '^[0-9a-f]{64}$'
        and storage_provider = 'CLOUDFLARE_R2'
        and bucket_name ~ '^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$'
        and nullif(btrim(object_key), '') is not null
        and object_key !~ '(^|/)\.\.?(/|$)'
        and object_key !~ '\\'
        and nullif(btrim(schema_version), '') is not null
        and parquet_sha256 ~ '^[0-9a-f]{64}$'
        and canonical_content_sha256 ~ '^[0-9a-f]{64}$'
        and byte_size > 0
        and market in ('TWSE', 'TPEX')
        and asset_type in ('COMMON_STOCK', 'ETF')
        and horizon = 5
        and min_trade_date <= max_trade_date
    ),
    constraint canonical_dataset_object_count_check check (
        source_row_count > 0
        and canonical_row_count > 0
        and rejected_row_count >= 0
        and quarantined_row_count >= 0
        and quarantined_row_count <= rejected_row_count
        and source_row_count = canonical_row_count + rejected_row_count
        and research_only_row_count = canonical_row_count
        and model_eligible_row_count = 0
    ),
    constraint canonical_dataset_object_lineage_check check (
        raw_parquet_sha256 ~ '^[0-9a-f]{64}$'
        and raw_manifest_snapshot_sha256 ~ '^[0-9a-f]{64}$'
        and build_input_snapshot_sha256 ~ '^[0-9a-f]{64}$'
        and (
            identity_snapshot_sha256 is null
            or identity_snapshot_sha256 ~ '^[0-9a-f]{64}$'
        )
        and (
            calendar_snapshot_sha256 is null
            or calendar_snapshot_sha256 ~ '^[0-9a-f]{64}$'
        )
        and (
            security_state_snapshot_sha256 is null
            or security_state_snapshot_sha256 ~ '^[0-9a-f]{64}$'
        )
        and (
            company_action_snapshot_sha256 is null
            or company_action_snapshot_sha256 ~ '^[0-9a-f]{64}$'
        )
        and nullif(btrim(builder_version), '') is not null
        and nullif(btrim(publication_rule_version), '') is not null
        and git_commit ~ '^[0-9a-f]{7,40}$'
        and jsonb_typeof(library_versions) = 'object'
        and jsonb_typeof(reason_counts) = 'object'
        and built_at <= ingested_at
        and (object_etag is null or nullif(btrim(object_etag), '') is not null)
    ),
    constraint canonical_dataset_object_raw_only_scope_check check (
        point_in_time_status = 'UNVERIFIED'
        and usage_scope = 'CANONICAL_RESEARCH_ONLY'
        and system_status = 'RESEARCH_ONLY'
        and cardinality(reason_codes) > 0
        and array_position(reason_codes, null) is null
        and model_eligible_row_count = 0
    )
);

create or replace function market_data.validate_canonical_dataset_raw_archive()
returns trigger
language plpgsql
security invoker
set search_path = pg_catalog
as $function$
declare
    raw_archive record;
begin
    select
        archive.parquet_sha256,
        archive.row_count,
        archive.quarantined_row_count,
        archive.scheduled_market,
        archive.asset_type,
        archive.min_trade_date,
        archive.max_trade_date,
        archive.point_in_time_status,
        archive.usage_scope,
        archive.system_status
    into raw_archive
    from market_data.historical_archive_objects as archive
    where archive.archive_key = new.raw_archive_key;

    if not found
       or raw_archive.parquet_sha256 <> new.raw_parquet_sha256
       or raw_archive.scheduled_market <> new.market
       or raw_archive.asset_type <> new.asset_type
       or new.min_trade_date < raw_archive.min_trade_date
       or new.max_trade_date > raw_archive.max_trade_date
       or new.source_row_count > raw_archive.row_count
       or new.quarantined_row_count > raw_archive.quarantined_row_count
       or raw_archive.point_in_time_status <> 'UNVERIFIED'
       or raw_archive.usage_scope <> 'RAW_LANDING_ONLY'
       or raw_archive.system_status <> 'RESEARCH_ONLY' then
        raise exception using
            errcode = '23514',
            message = 'canonical research object conflicts with raw archive';
    end if;

    return new;
end
$function$;

drop trigger if exists canonical_dataset_objects_validate_raw_archive
on market_data.canonical_dataset_objects;
create trigger canonical_dataset_objects_validate_raw_archive
before insert on market_data.canonical_dataset_objects
for each row execute function
market_data.validate_canonical_dataset_raw_archive();

revoke all on function
market_data.validate_canonical_dataset_raw_archive()
from public, anon, authenticated;

-- noqa: disable=PG01
create unique index if not exists canonical_dataset_objects_build_uidx
on market_data.canonical_dataset_objects (
    raw_archive_key,
    build_input_snapshot_sha256,
    builder_version,
    schema_version
);

create index if not exists canonical_dataset_objects_coverage_idx
on market_data.canonical_dataset_objects (
    market,
    asset_type,
    horizon,
    min_trade_date,
    max_trade_date
);

create index if not exists canonical_dataset_objects_raw_snapshot_idx
on market_data.canonical_dataset_objects (
    raw_manifest_snapshot_sha256,
    raw_archive_key
);

create index if not exists canonical_dataset_objects_publication_snapshot_idx
on market_data.canonical_dataset_objects (publication_snapshot_id)
where publication_snapshot_id is not null;
-- noqa: enable=PG01

comment on table market_data.canonical_dataset_objects is
'Append-only manifest for research-only canonical Parquet objects in private
Cloudflare R2. The first contract cannot produce model-eligible rows.';
comment on column
market_data.canonical_dataset_objects.model_eligible_row_count is
'Hard-coded by database constraint to zero for the raw-only canonical research
builder. A future verified builder requires a separate reviewed migration.';
comment on column
market_data.canonical_dataset_objects.raw_manifest_snapshot_sha256 is
'Digest of the complete meaning-bearing raw manifest snapshot audited before
the canonical build started.';

drop trigger if exists canonical_dataset_objects_append_only
on market_data.canonical_dataset_objects;
create trigger canonical_dataset_objects_append_only
before update or delete on market_data.canonical_dataset_objects
for each row execute function market_data.reject_pit_contract_mutation();

alter table market_data.canonical_dataset_objects enable row level security;
alter table market_data.canonical_dataset_objects force row level security;

revoke all on market_data.canonical_dataset_objects
from public, anon, authenticated, service_role;
revoke all on sequence
market_data.canonical_dataset_objects_canonical_object_id_seq
from public, anon, authenticated, service_role;

grant select, insert on market_data.canonical_dataset_objects to service_role;
grant usage, select on sequence
market_data.canonical_dataset_objects_canonical_object_id_seq
to service_role;

commit;

notify pgrst, 'reload schema';

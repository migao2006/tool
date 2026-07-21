begin;

create extension if not exists btree_gist with schema extensions;
set local search_path = pg_catalog, public, extensions;

create table if not exists market_data.security_listing_periods (
    listing_evidence_id bigint generated always as identity primary key,
    listing_period_id text not null,
    security_id bigint
    references market_data.securities (security_id) on delete restrict,
    listing_market text not null,
    asset_type text not null,
    source_symbol text not null,
    source_name text,
    isin text,
    effective_from date not null,
    effective_to date,
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
    constraint security_listing_periods_identity_check check (
        listing_market in ('TWSE', 'TPEX')
        and asset_type in ('COMMON_STOCK', 'ETF')
        and nullif(btrim(listing_period_id), '') is not null
        and length(listing_period_id) <= 128
        and nullif(btrim(source_symbol), '') is not null
        and length(source_symbol) <= 32
        and (source_name is null or nullif(btrim(source_name), '') is not null)
        and (isin is null or isin ~ '^[A-Z0-9]{12}$')
        and (effective_to is null or effective_to > effective_from)
        and identity_resolution_status in ('VERIFIED', 'UNRESOLVED', 'CONFLICT')
    ),
    constraint security_listing_periods_lineage_check check (
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
    constraint security_listing_periods_status_check check (
        array_position(reason_codes, null) is null
        and (
            (
                identity_resolution_status = 'VERIFIED'
                and security_id is not null
                and isin is not null
                and available_at_basis in (
                    'OFFICIAL_PUBLICATION_AT',
                    'VERSIONED_SNAPSHOT'
                )
                and usage_scope = 'POINT_IN_TIME_IDENTITY'
                and system_status = 'PASS'
                and cardinality(reason_codes) = 0
            )
            or (
                identity_resolution_status in ('UNRESOLVED', 'CONFLICT')
                and security_id is null
                and usage_scope = 'IDENTITY_RESEARCH_ONLY'
                and system_status in ('RESEARCH_ONLY', 'FAIL')
                and cardinality(reason_codes) > 0
            )
        )
    ),
    constraint security_listing_periods_verified_symbol_no_overlap
    exclude using gist (
        listing_market with =,
        source_symbol with =,
        daterange(effective_from, effective_to, '[)') with &&
    ) where (identity_resolution_status = 'VERIFIED'),
    constraint security_listing_periods_verified_security_no_overlap
    exclude using gist (
        security_id with =,
        daterange(effective_from, effective_to, '[)') with &&
    ) where (identity_resolution_status = 'VERIFIED')
);

-- noqa: disable=PG01
create unique index if not exists security_listing_periods_source_revision_uidx
on market_data.security_listing_periods (
    source_id,
    source_dataset,
    source_event_id,
    source_revision_hash
);

create unique index if not exists security_listing_periods_verified_episode_uidx
on market_data.security_listing_periods (listing_period_id)
where identity_resolution_status = 'VERIFIED';

create index if not exists security_listing_periods_symbol_date_idx
on market_data.security_listing_periods (
    listing_market,
    asset_type,
    source_symbol,
    effective_from,
    effective_to
);

create index if not exists security_listing_periods_verified_security_idx
on market_data.security_listing_periods (
    security_id,
    listing_period_id,
    effective_from,
    effective_to,
    available_at
)
where identity_resolution_status = 'VERIFIED';
-- noqa: enable=PG01

comment on table market_data.security_listing_periods is
'Append-only historical listing identity evidence. A later contradiction is
inserted as CONFLICT and never overwrites an existing VERIFIED period.';
comment on column market_data.security_listing_periods.source_name is
'Display name exactly as observed in the source evidence; it is not canonical.';
comment on column market_data.security_listing_periods.effective_to is
'Exclusive upper bound. Null means that the listing period remains open.';
comment on column market_data.security_listing_periods.available_at is
'Earliest evidenced availability. VERSIONED_SNAPSHOT is eligible only from
its first_observed_at onward and never backdates historical availability.';

create or replace function market_data.reject_pit_contract_mutation()
returns trigger
language plpgsql
security invoker
set search_path = pg_catalog
as $function$
begin
  raise exception using
    errcode = '55000',
    message = format('%I.%I is append-only', tg_table_schema, tg_table_name);
end
$function$;

create or replace function market_data.validate_verified_listing_identity()
returns trigger
language plpgsql
security invoker
set search_path = pg_catalog
as $function$
begin
  if new.identity_resolution_status = 'VERIFIED'
     and not exists (
       select 1
       from market_data.securities as security
       where security.security_id = new.security_id
         and security.market = new.listing_market
         and security.asset_type = new.asset_type
         and security.symbol = new.source_symbol
         and security.isin = new.isin
     ) then
    raise exception using
      errcode = '23514',
      message = 'VERIFIED listing identity conflicts with canonical security';
  end if;
  return new;
end
$function$;

drop trigger if exists security_listing_periods_validate_identity
on market_data.security_listing_periods;
create trigger security_listing_periods_validate_identity
before insert on market_data.security_listing_periods
for each row execute function market_data.validate_verified_listing_identity();

drop trigger if exists security_listing_periods_append_only
on market_data.security_listing_periods;
create trigger security_listing_periods_append_only
before update or delete on market_data.security_listing_periods
for each row execute function market_data.reject_pit_contract_mutation();

alter table market_data.security_listing_periods enable row level security;
alter table market_data.security_listing_periods force row level security;

revoke all on market_data.security_listing_periods
from public, anon, authenticated, service_role;
revoke all on sequence
market_data.security_listing_periods_listing_evidence_id_seq
from public, anon, authenticated, service_role;
revoke all on function market_data.reject_pit_contract_mutation()
from public, anon, authenticated;
revoke all on function market_data.validate_verified_listing_identity()
from public, anon, authenticated;

grant select, insert on market_data.security_listing_periods to service_role;
grant usage, select
on sequence
market_data.security_listing_periods_listing_evidence_id_seq
to service_role;

commit;

notify pgrst, 'reload schema';

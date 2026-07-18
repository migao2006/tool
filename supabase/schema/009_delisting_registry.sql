begin;

set local search_path = pg_catalog, public, extensions;

create table if not exists market_data.delisting_registry_observations (
  delisting_observation_id bigint generated always as identity primary key,
  listing_market text not null,
  source_symbol text not null,
  source_name text,
  termination_date date not null,
  termination_reason_raw text,
  source_id bigint not null
    references market_data.data_sources(source_id),
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
  record_status text not null,
  identity_resolution_status text not null,
  usage_scope text not null,
  system_status text not null,
  reason_codes text[] not null,
  ingested_at timestamptz not null default now(),
  constraint delisting_registry_contract_check check (
    listing_market in ('TWSE', 'TPEX')
    and nullif(btrim(source_symbol), '') is not null
    and length(source_symbol) <= 32
    and (source_name is null or nullif(btrim(source_name), '') is not null)
    and nullif(btrim(source_dataset), '') is not null
    and nullif(btrim(source_event_id), '') is not null
    and nullif(btrim(source_version), '') is not null
    and source_revision_hash ~ '^[0-9a-f]{64}$'
    and source_payload_hash ~ '^[0-9a-f]{64}$'
    and source_url ~ '^https://'
    and jsonb_typeof(source_row) = 'object'
    and available_at = first_observed_at
    and available_at_basis = 'FIRST_OBSERVED_AT_RETRIEVAL'
    and record_status = 'VERIFIED_DELISTING'
    and identity_resolution_status = 'UNRESOLVED'
    and usage_scope = 'IDENTITY_RESEARCH_ONLY'
    and system_status = 'RESEARCH_ONLY'
    and cardinality(reason_codes) > 0
  )
);

create unique index if not exists delisting_registry_revision_uidx
  on market_data.delisting_registry_observations (
    source_id,
    source_dataset,
    source_event_id,
    source_revision_hash
  );

create index if not exists delisting_registry_event_lookup_idx
  on market_data.delisting_registry_observations (
    listing_market,
    source_symbol,
    termination_date
  );

create index if not exists delisting_registry_source_id_idx
  on market_data.delisting_registry_observations (source_id);

create index if not exists delisting_registry_available_at_idx
  on market_data.delisting_registry_observations (available_at);

comment on table market_data.delisting_registry_observations is
  'Official delisting source events kept unresolved until immutable security identity evidence exists.';
comment on column market_data.delisting_registry_observations.available_at is
  'Project first-retrieval time, not the historical announcement or termination time.';
comment on column market_data.delisting_registry_observations.source_symbol is
  'Source symbol only; it must not be joined to the current security master without identity resolution.';

alter table market_data.delisting_registry_observations enable row level security;

revoke all on market_data.delisting_registry_observations
  from public, anon, authenticated;
grant select, insert, update, delete
  on market_data.delisting_registry_observations to service_role;
grant usage, select
  on sequence market_data.delisting_registry_observations_delisting_observation_id_seq
  to service_role;

commit;

notify pgrst, 'reload schema';

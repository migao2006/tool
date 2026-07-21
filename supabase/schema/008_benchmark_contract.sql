begin;

set local search_path = pg_catalog, public, extensions;

alter table market_data.benchmark_definitions
  add column if not exists source_id bigint
    references market_data.data_sources(source_id),
  add column if not exists source_dataset text,
  add column if not exists source_version text,
  add column if not exists source_revision_hash text,
  add column if not exists return_basis text,
  add column if not exists observation_frequency text,
  add column if not exists return_convention text,
  add column if not exists target_trade_path text,
  add column if not exists alignment_status text,
  add column if not exists usage_scope text,
  add column if not exists system_status text,
  add column if not exists reason_codes text[] not null default '{}'::text[];

do $$
begin
  if exists (
    select 1
    from market_data.benchmark_definitions
    where source_id is null
       or nullif(btrim(source_dataset), '') is null
       or nullif(btrim(source_version), '') is null
       or source_revision_hash is null
  ) then
    raise exception using
      errcode = '23502',
      message = 'Existing benchmark definitions need verified provenance before migration';
  end if;
end $$;

alter table market_data.benchmark_definitions
  alter column source_id set not null,
  alter column source_dataset set not null,
  alter column source_version set not null,
  alter column source_revision_hash set not null,
  alter column return_basis set not null,
  alter column observation_frequency set not null,
  alter column return_convention set not null,
  alter column target_trade_path set not null,
  alter column alignment_status set not null,
  alter column usage_scope set not null,
  alter column system_status set not null;

alter table market_data.benchmark_definitions
  drop constraint if exists benchmark_definitions_check;
alter table market_data.benchmark_definitions
  drop constraint if exists benchmark_definitions_effective_range_check;
alter table market_data.benchmark_definitions
  add constraint benchmark_definitions_effective_range_check
  check (effective_to is null or effective_to > effective_from);

alter table market_data.benchmark_definitions
  drop constraint if exists benchmark_definitions_contract_check;
alter table market_data.benchmark_definitions
  add constraint benchmark_definitions_contract_check
  check (
    source_revision_hash ~ '^[0-9a-f]{64}$'
    and return_basis = 'TOTAL_RETURN_INDEX'
    and observation_frequency = 'DAILY_CLOSE'
    and return_convention = 'CLOSE_TO_CLOSE'
    and target_trade_path = 'T_PLUS_1_OPEN_TO_H_CLOSE'
    and alignment_status = 'RESEARCH_ONLY'
    and usage_scope = 'LABEL_TARGET_ONLY'
    and system_status = 'RESEARCH_ONLY'
    and cardinality(reason_codes) > 0
  );

alter table market_data.benchmark_definitions
  drop constraint if exists benchmark_definitions_no_overlapping_market_ranges;
alter table market_data.benchmark_definitions
  add constraint benchmark_definitions_no_overlapping_market_ranges
  exclude using gist (
    market with =,
    daterange(effective_from, effective_to, '[)') with &&
  );

create index if not exists benchmark_definitions_source_id_idx
  on market_data.benchmark_definitions (source_id);

alter table market_data.market_observations
  add column if not exists benchmark_id bigint
    references market_data.benchmark_definitions(benchmark_id),
  add column if not exists source_dataset text,
  add column if not exists observation_kind text,
  add column if not exists first_observed_at timestamptz,
  add column if not exists available_at_basis text,
  add column if not exists usage_scope text,
  add column if not exists alignment_status text,
  add column if not exists reason_codes text[] not null default '{}'::text[],
  add column if not exists source_revision_hash text,
  add column if not exists source_payload_hash text;

alter table market_data.market_observations
  drop constraint if exists market_observations_benchmark_contract_check;
alter table market_data.market_observations
  add constraint market_observations_benchmark_contract_check
  check (
    benchmark_id is null
    or (
      nullif(btrim(source_dataset), '') is not null
      and observation_kind = 'TOTAL_RETURN_INDEX_LEVEL'
      and numeric_value is not null
      and numeric_value > 0
      and text_value is null
      and first_observed_at is not null
      and available_at >= first_observed_at
      and available_at_basis = 'FIRST_OBSERVED_AT_RETRIEVAL'
      and usage_scope = 'LABEL_TARGET_ONLY'
      and alignment_status = 'RESEARCH_ONLY'
      and cardinality(reason_codes) > 0
      and source_revision_hash is not null
      and source_revision_hash ~ '^[0-9a-f]{64}$'
      and source_payload_hash is not null
      and source_payload_hash ~ '^[0-9a-f]{64}$'
    )
  );

create unique index if not exists market_observations_benchmark_revision_uidx
  on market_data.market_observations (
    series_code,
    observation_at,
    source_id,
    source_revision_hash
  );

create index if not exists market_observations_benchmark_id_idx
  on market_data.market_observations (benchmark_id);

comment on column market_data.benchmark_definitions.effective_to is
  'Exclusive upper bound. Null means the definition remains effective.';
comment on column market_data.benchmark_definitions.alignment_status is
  'RESEARCH_ONLY because close-to-close index returns do not match the stock execution path.';
comment on column market_data.market_observations.benchmark_id is
  'Null for generic series; populated only for audited benchmark observations.';
comment on column market_data.market_observations.first_observed_at is
  'First project retrieval time, not an exchange row-level publication time.';

commit;

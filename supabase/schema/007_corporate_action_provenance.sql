begin;

alter table market_data.corporate_actions
  add column if not exists action_status text not null default 'UNKNOWN',
  add column if not exists available_at_basis text not null default 'UNKNOWN',
  add column if not exists first_observed_at timestamptz,
  add column if not exists source_row_complete boolean not null default false,
  add column if not exists source_dataset text not null default 'UNKNOWN',
  add column if not exists source_action_label text,
  add column if not exists source_event_id text,
  add column if not exists source_revision_hash text,
  add column if not exists source_payload_hash text,
  add column if not exists share_multiplier numeric(20,10),
  add column if not exists reason_codes text[] not null default '{}'::text[];

update market_data.corporate_actions
set first_observed_at = available_at
where first_observed_at is null;

update market_data.corporate_actions
set source_event_id = 'legacy:' || corporate_action_id::text
where source_event_id is null;

alter table market_data.corporate_actions
  alter column first_observed_at set not null,
  alter column source_event_id set not null,
  alter column announced_at drop not null;

alter table market_data.corporate_actions
  drop constraint if exists corporate_actions_check;
alter table market_data.corporate_actions
  drop constraint if exists corporate_actions_available_times_check;
alter table market_data.corporate_actions
  add constraint corporate_actions_available_times_check
  check (
    available_at >= first_observed_at
    and (announced_at is null or available_at >= announced_at)
  );

alter table market_data.corporate_actions
  drop constraint if exists corporate_actions_action_status_check;
alter table market_data.corporate_actions
  add constraint corporate_actions_action_status_check
  check (action_status in ('UNKNOWN', 'ANNOUNCED', 'REALIZED', 'CANCELLED'));

alter table market_data.corporate_actions
  drop constraint if exists corporate_actions_available_at_basis_check;
alter table market_data.corporate_actions
  add constraint corporate_actions_available_at_basis_check
  check (
    available_at_basis in (
      'UNKNOWN',
      'SOURCE_PUBLISHED_AT',
      'FIRST_OBSERVED_AT_RETRIEVAL'
    )
  );

alter table market_data.corporate_actions
  drop constraint if exists corporate_actions_source_revision_hash_check;
alter table market_data.corporate_actions
  add constraint corporate_actions_source_revision_hash_check
  check (
    source_revision_hash is null
    or source_revision_hash ~ '^[0-9a-f]{64}$'
  );

alter table market_data.corporate_actions
  drop constraint if exists corporate_actions_source_payload_hash_check;
alter table market_data.corporate_actions
  add constraint corporate_actions_source_payload_hash_check
  check (
    source_payload_hash is null
    or source_payload_hash ~ '^[0-9a-f]{64}$'
  );

alter table market_data.corporate_actions
  drop constraint if exists corporate_actions_share_multiplier_check;
alter table market_data.corporate_actions
  add constraint corporate_actions_share_multiplier_check
  check (share_multiplier is null or share_multiplier > 0);

create unique index if not exists corporate_actions_source_revision_uidx
  on market_data.corporate_actions (
    source_id,
    source_event_id,
    source_revision_hash
  );

comment on column market_data.corporate_actions.action_status is
  'ANNOUNCED is a forecast and must not be treated as a realized entitlement.';
comment on column market_data.corporate_actions.available_at_basis is
  'FIRST_OBSERVED_AT_RETRIEVAL prevents unknown publication times from being backdated.';
comment on column market_data.corporate_actions.first_observed_at is
  'First time this project retrieved the source version; not the issuer announcement time.';
comment on column market_data.corporate_actions.source_row_complete is
  'False means the complete lifecycle and all settlement terms are not verified.';
comment on column market_data.corporate_actions.share_multiplier is
  'Canonical post-action shares per pre-action share; stock dividend uses 1 + source share_ratio.';
comment on column market_data.corporate_actions.source_revision_hash is
  'SHA-256 of the canonical source event row, independent of unrelated payload rows.';
comment on column market_data.corporate_actions.source_payload_hash is
  'SHA-256 of the complete provider response used to audit the source snapshot.';

commit;

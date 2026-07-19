do $$
declare
  validation_source_id bigint;
  validation_security_id bigint;
begin
  insert into market_data.data_sources (
    source_code,
    display_name,
    source_timezone,
    revision_policy
  ) values (
    'VALIDATION_LATE_SECURITY_SNAPSHOT',
    'Validation only',
    'Asia/Taipei',
    'VALIDATION_ONLY'
  )
  returning source_id into validation_source_id;

  insert into market_data.securities (
    symbol,
    display_name,
    market,
    asset_type,
    source_id
  ) values (
    'V0001',
    'Validation only',
    'TWSE',
    'COMMON_STOCK',
    validation_source_id
  )
  returning security_id into validation_security_id;

  insert into market_data.security_history (
    security_id,
    effective_from,
    effective_to,
    trading_status,
    source_id,
    source_version,
    available_at,
    record_kind,
    snapshot_date,
    source_revision_hash
  ) values (
    validation_security_id,
    date '2026-07-17',
    date '2026-07-18',
    'ACTIVE',
    validation_source_id,
    'validation-v1',
    timestamptz '2026-07-19 06:00:00+00',
    'CURRENT_DAILY_SNAPSHOT',
    date '2026-07-17',
    repeat('a', 64)
  );

  begin
    insert into market_data.security_history (
      security_id,
      effective_from,
      effective_to,
      trading_status,
      source_id,
      source_version,
      available_at,
      record_kind,
      snapshot_date,
      source_revision_hash
    ) values (
      validation_security_id,
      date '2026-07-20',
      date '2026-07-21',
      'ACTIVE',
      validation_source_id,
      'validation-v1',
      timestamptz '2026-07-19 06:00:00+00',
      'CURRENT_DAILY_SNAPSHOT',
      date '2026-07-20',
      repeat('b', 64)
    );

    raise exception 'FUTURE_SECURITY_SNAPSHOT_WAS_NOT_REJECTED';
  exception
    when check_violation then
      null;
  end;

  delete from market_data.security_history
  where security_id = validation_security_id;
  delete from market_data.securities
  where security_id = validation_security_id;
  delete from market_data.data_sources
  where source_id = validation_source_id;
end;
$$;

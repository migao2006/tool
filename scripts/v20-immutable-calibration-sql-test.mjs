import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { PGlite } from "@electric-sql/pglite";
import { pgcrypto } from "@electric-sql/pglite/contrib/pgcrypto";

const migrationUrl = new URL(
  "../supabase/migrations/20260716182335_add_v20_immutable_calibration_snapshots.sql",
  import.meta.url,
);
const sql = await readFile(migrationUrl, "utf8");

for (const contract of [
  /create table if not exists public\.v20_calibration_snapshots/i,
  /create table if not exists public\.v20_calibration_snapshot_buckets/i,
  /twss_v20_refresh_immutable_calibration\s*\(/i,
  /twss_v20_read_immutable_calibration\s*\(/i,
  /latest_revision_recorded_at_or_before_cutoff/i,
  /minimum_sample_count[^;]+>= 100/is,
  /empirical_beta_1_1/i,
  /before update or delete on public\.v20_calibration_snapshots/i,
  /revoke all on function public\.twss_v20_refresh_immutable_calibration\(jsonb\)[\s\S]+from public, anon, authenticated, service_role/i,
]) {
  assert.match(sql, contract);
}
assert.doesNotMatch(
  sql,
  /(?:from|join)\s+public\.v20_calibration_buckets\b/i,
  "v20.1 calibration must not read the legacy mutable bucket table",
);

const db = new PGlite({ extensions: { pgcrypto } });

try {
  await db.exec(`
    create role anon;
    create role authenticated;
    create role service_role bypassrls;
    create schema extensions;
    create extension pgcrypto with schema extensions;

    create table public.v20_calibration_buckets (
      model_key text,
      sample_count integer,
      calibrated_probability numeric
    );
    insert into public.v20_calibration_buckets values ('short', 999999, 99.99);

    create table public.v20_recommendation_runs (
      id bigint generated always as identity primary key,
      data_date date not null,
      data_cutoff_at timestamptz not null,
      revision integer not null,
      status text not null,
      model_version text not null,
      calibration_version text,
      market_regime text,
      content_hash text not null,
      published_at timestamptz not null
    );

    create table public.v20_recommendation_items (
      id bigint generated always as identity primary key,
      run_id bigint not null references public.v20_recommendation_runs(id),
      signal_date date not null,
      model_key text not null,
      horizon_days integer not null,
      model_version text not null,
      strategy_key text not null,
      is_eligible boolean not null,
      public_visible boolean not null,
      research_only boolean not null,
      net_opportunity_score numeric not null,
      input_hash text not null
    );

    create table public.v20_outcome_observations (
      id bigint generated always as identity primary key,
      recommendation_item_id bigint not null references public.v20_recommendation_items(id),
      observed_horizon_days integer not null,
      revision integer not null,
      entry_date date not null,
      exit_date date not null,
      gross_return numeric not null,
      net_return numeric not null,
      excess_return_net numeric not null,
      mfe numeric,
      mae numeric,
      target_hit_first boolean,
      observation_hash text not null,
      observed_at timestamptz not null,
      recorded_at timestamptz not null
    );

    create or replace function public.twss_v20_reject_immutable_change()
    returns trigger language plpgsql set search_path = '' as $$
    begin
      raise exception 'v20_immutable_record' using errcode = '55000';
    end;
    $$;

    grant select on table
      public.v20_recommendation_runs,
      public.v20_recommendation_items,
      public.v20_outcome_observations
    to service_role;
  `);

  await db.exec(sql);

  await db.exec(`
    insert into public.v20_recommendation_runs (
      data_date, data_cutoff_at, revision, status, model_version,
      market_regime, content_hash, published_at
    ) values (
      current_date - 20,
      pg_catalog.timezone('Asia/Taipei', (current_date - 19)::timestamp) - interval '8 hours',
      1,
      'published',
      '20.1',
      'sideways',
      repeat('a', 64),
      pg_catalog.timezone('Asia/Taipei', (current_date - 19)::timestamp) - interval '6 hours'
    );

    insert into public.v20_recommendation_items (
      run_id, signal_date, model_key, horizon_days, model_version,
      strategy_key, is_eligible, public_visible, research_only,
      net_opportunity_score, input_hash
    )
    select
      1,
      current_date - 20,
      'short',
      2,
      '20.1',
      'momentum_breakout',
      true,
      true,
      false,
      85,
      pg_catalog.encode(extensions.digest('item-' || g::text, 'sha256'), 'hex')
    from generate_series(1, 160) g;

    -- Revision 1 has 80/160 cost-after wins.
    insert into public.v20_outcome_observations (
      recommendation_item_id, observed_horizon_days, revision,
      entry_date, exit_date, gross_return, net_return, excess_return_net,
      mfe, mae, target_hit_first, observation_hash, observed_at, recorded_at
    )
    select
      g,
      2,
      1,
      current_date - 19,
      current_date - 17,
      case when g <= 80 then 2 else -2 end,
      case when g <= 80 then 1 else -3 end,
      case when g <= 80 then 0.8 else -3.2 end,
      3,
      -2,
      g <= 80,
      pg_catalog.encode(extensions.digest('outcome-r1-' || g::text, 'sha256'), 'hex'),
      current_date - 14,
      current_date - 14
    from generate_series(1, 160) g;

    -- Revisions available before cutoff 1 replace 20 wins with losses.
    insert into public.v20_outcome_observations (
      recommendation_item_id, observed_horizon_days, revision,
      entry_date, exit_date, gross_return, net_return, excess_return_net,
      mfe, mae, target_hit_first, observation_hash, observed_at, recorded_at
    )
    select
      g,
      2,
      2,
      current_date - 19,
      current_date - 17,
      -2,
      -3,
      -3.2,
      1,
      -4,
      false,
      pg_catalog.encode(extensions.digest('outcome-r2-' || g::text, 'sha256'), 'hex'),
      current_date - 12,
      current_date - 12
    from generate_series(1, 20) g;

    -- These ten corrections are after cutoff 1 but before cutoff 2.
    insert into public.v20_outcome_observations (
      recommendation_item_id, observed_horizon_days, revision,
      entry_date, exit_date, gross_return, net_return, excess_return_net,
      mfe, mae, target_hit_first, observation_hash, observed_at, recorded_at
    )
    select
      g,
      2,
      3,
      current_date - 19,
      current_date - 17,
      2,
      1,
      0.8,
      3,
      -1,
      true,
      pg_catalog.encode(extensions.digest('outcome-r3-' || g::text, 'sha256'), 'hex'),
      current_date - 8,
      current_date - 8
    from generate_series(1, 10) g;
  `);

  const cutoffs = (
    await db.query(`
      select
        (current_date - 10 + time '12:00')::timestamptz::text cutoff_1,
        (current_date - 5 + time '12:00')::timestamptz::text cutoff_2,
        (current_date - 25 + time '12:00')::timestamptz::text before_any
    `)
  ).rows[0];

  const privileges = (
    await db.query(`
      select
        has_table_privilege('anon', 'public.v20_calibration_snapshots', 'select') anon_table,
        has_function_privilege(
          'anon', 'public.twss_v20_refresh_immutable_calibration(jsonb)', 'execute'
        ) anon_refresh,
        has_function_privilege(
          'service_role', 'public.twss_v20_refresh_immutable_calibration(jsonb)', 'execute'
        ) service_refresh,
        has_function_privilege(
          'service_role', 'public.twss_v20_read_immutable_calibration(jsonb)', 'execute'
        ) service_read
    `)
  ).rows[0];
  assert.deepEqual(privileges, {
    anon_table: false,
    anon_refresh: false,
    service_refresh: true,
    service_read: true,
  });

  await db.exec("set role service_role");
  const request1 = {
    cutoffAt: cutoffs.cutoff_1,
    modelVersion: "20.1",
    minimumSampleCount: 5,
    maximumObservationCount: 500,
  };
  const first = (
    await db.query(
      "select public.twss_v20_refresh_immutable_calibration($1::jsonb) result",
      [JSON.stringify(request1)],
    )
  ).rows[0].result;
  const repeated = (
    await db.query(
      "select public.twss_v20_refresh_immutable_calibration($1::jsonb) result",
      [JSON.stringify(request1)],
    )
  ).rows[0].result;

  assert.equal(first.status, "ready");
  assert.equal(first.sourceObservationCount, 160);
  assert.equal(first.minimumSampleCount, 100);
  assert.equal(first.bucketCount, 2);
  assert.equal(first.idempotent, false);
  assert.equal(repeated.calibrationVersion, first.calibrationVersion);
  assert.equal(repeated.idempotent, true);

  const read1 = (
    await db.query(
      "select public.twss_v20_read_immutable_calibration($1::jsonb) result",
      [JSON.stringify({ beforeAt: cutoffs.cutoff_1, modelVersion: "20.1" })],
    )
  ).rows[0].result;
  assert.equal(read1.status, "ready");
  assert.equal(read1.calibrationVersion, first.calibrationVersion);
  assert.equal(read1.buckets.length, 2);
  const exact1 = read1.buckets.find((bucket) => bucket.strategy_key === "momentum_breakout");
  const fallback1 = read1.buckets.find((bucket) => bucket.strategy_key === "all");
  assert.equal(exact1.score_decile, 8);
  assert.equal(exact1.sample_count, 160);
  assert.equal(exact1.wins, 60);
  assert.equal(exact1.raw_probability, 37.5);
  assert.equal(exact1.calibrated_probability, 37.654321);
  assert.equal(fallback1.score_decile, -1);
  assert.equal(fallback1.minimum_sample_count, 150);
  assert.equal(exact1.average_excess_return_gross, null);

  const beforeAny = (
    await db.query(
      "select public.twss_v20_read_immutable_calibration($1::jsonb) result",
      [JSON.stringify({ beforeAt: cutoffs.before_any, modelVersion: "20.1" })],
    )
  ).rows[0].result;
  assert.equal(beforeAny.status, "not_ready");
  assert.deepEqual(beforeAny.buckets, []);

  const second = (
    await db.query(
      "select public.twss_v20_refresh_immutable_calibration($1::jsonb) result",
      [JSON.stringify({ ...request1, cutoffAt: cutoffs.cutoff_2 })],
    )
  ).rows[0].result;
  assert.notEqual(second.calibrationVersion, first.calibrationVersion);
  const read2 = (
    await db.query(
      "select public.twss_v20_read_immutable_calibration($1::jsonb) result",
      [JSON.stringify({ beforeAt: cutoffs.cutoff_2, modelVersion: "20.1" })],
    )
  ).rows[0].result;
  const exact2 = read2.buckets.find((bucket) => bucket.strategy_key === "momentum_breakout");
  assert.equal(exact2.sample_count, 160);
  assert.equal(exact2.wins, 70);
  assert.equal(exact2.raw_probability, 43.75);

  await db.exec("reset role");
  await assert.rejects(
    db.exec("update public.v20_calibration_snapshots set bucket_count = 999"),
    /v20_immutable_record/,
  );
  await assert.rejects(
    db.exec("delete from public.v20_calibration_snapshot_buckets"),
    /v20_immutable_record/,
  );

  console.log("v20 immutable calibration SQL checks passed", {
    snapshots: 2,
    sourceObservations: first.sourceObservationCount,
    cutoff1Wins: exact1.wins,
    cutoff2Wins: exact2.wins,
    calibrationVersion: first.calibrationVersion,
  });
} finally {
  await db.close();
}

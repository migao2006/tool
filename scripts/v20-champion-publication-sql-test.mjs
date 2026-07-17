import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { PGlite } from "@electric-sql/pglite";
import { pgcrypto } from "@electric-sql/pglite/contrib/pgcrypto";
import { buildV20PublicationManifests } from "../supabase/functions/_shared/v20-publication-contract.js";

const immutableMigrationUrl = new URL(
  "../supabase/migrations/20260716173332_verifiable_opportunity_snapshots.sql",
  import.meta.url,
);
const bindingMigrationUrl = new URL(
  "../supabase/migrations/20260716184000_bind_publications_to_champion_releases.sql",
  import.meta.url,
);

const db = new PGlite({ extensions: { pgcrypto } });
const artifactA = "a".repeat(64);
const artifactB = "b".repeat(64);
const artifactC = "c".repeat(64);
const artifactD = "d".repeat(64);
const calibrationVersion = `twss-cal-sha256-${"c".repeat(64)}`;

const prerequisiteSql = `
  create role anon;
  create role authenticated;
  create role service_role bypassrls;
  create role supabase_admin;
  create schema extensions;
  create extension pgcrypto with schema extensions;

  create table public.stock_master (symbol text primary key);

  create table public.v20_market_context (
    data_date date not null,
    model_version text not null,
    regime text not null,
    regime_score numeric not null,
    confidence numeric not null,
    completeness numeric not null,
    status text not null,
    taiex jsonb not null,
    tpex jsonb not null,
    tx_futures jsonb not null,
    breadth jsonb not null,
    institutional jsonb not null,
    global_context jsonb not null,
    source_dates jsonb not null,
    degraded_sources text[] not null,
    fetched_at timestamptz,
    generated_at timestamptz not null default clock_timestamp(),
    updated_at timestamptz not null default clock_timestamp(),
    primary key (data_date, model_version)
  );

  create table public.v20_model_signals (
    symbol text references public.stock_master(symbol),
    signal_date date,
    model_key text,
    horizon_days integer,
    model_version text,
    group_name text,
    name text,
    market text,
    industry text,
    instrument_type text,
    strategy_key text,
    opportunity_score numeric,
    risk_score numeric,
    confidence numeric,
    completeness numeric,
    official boolean,
    gate_passed boolean,
    gate_results jsonb,
    feature_scores jsonb,
    prediction_basis text,
    up_probability numeric,
    expected_return_net numeric,
    return_p10 numeric,
    return_p50 numeric,
    return_p90 numeric,
    mfe numeric,
    mae numeric,
    target_first_probability numeric,
    entry_low numeric,
    entry_high numeric,
    breakout_price numeric,
    no_chase_price numeric,
    stop_loss numeric,
    take_profit_1 numeric,
    take_profit_2 numeric,
    risk_reward_ratio numeric,
    expected_value numeric,
    recommended_holding_days integer,
    recommended_action text,
    reasons jsonb,
    risks jsonb,
    invalidation_conditions jsonb,
    source_dates jsonb,
    generated_at timestamptz default clock_timestamp(),
    updated_at timestamptz default clock_timestamp(),
    primary key (symbol, signal_date, model_key, horizon_days, model_version),
    check (
      (model_key = 'short' and horizon_days in (2, 3, 5, 10))
      or (model_key = 'medium' and horizon_days in (20, 40, 60))
    )
  );

  create table public.v20_ranking_snapshots (
    model_key text,
    horizon_days integer,
    check (
      (model_key = 'short' and horizon_days in (2, 3, 5, 10))
      or (model_key = 'medium' and horizon_days in (20, 40, 60))
    )
  );
  create table public.v20_backtest_runs (
    id bigint generated always as identity primary key,
    model_key text,
    horizon_days integer,
    check (
      (model_key = 'short' and horizon_days in (2, 3, 5, 10))
      or (model_key = 'medium' and horizon_days in (20, 40, 60))
    )
  );
  create table public.v20_calibration_buckets (
    model_key text,
    horizon_days integer,
    check (
      (model_key = 'short' and horizon_days in (2, 3, 5, 10))
      or (model_key = 'medium' and horizon_days in (20, 40, 60))
    )
  );
  create table public.v20_signal_outcomes (
    model_key text,
    horizon_days integer,
    check (
      (model_key = 'short' and horizon_days in (2, 3, 5, 10))
      or (model_key = 'medium' and horizon_days in (20, 40, 60))
    )
  );
  create table public.v20_backtest_outcomes (model_key text, horizon_days integer);

  create table public.v20_universe_membership (
    symbol text references public.stock_master(symbol),
    as_of_date date,
    model_version text,
    group_name text,
    name text,
    market text,
    industry text,
    instrument_type text,
    active boolean,
    eligible_short boolean,
    eligible_medium boolean,
    inclusion_reasons jsonb,
    exclusion_reasons jsonb,
    source_dates jsonb,
    updated_at timestamptz,
    primary key (symbol, as_of_date, model_version)
  );

  create table public.v20_model_dirty_queue (
    id bigint generated always as identity primary key,
    symbol text,
    data_date date,
    group_name text,
    model_version text,
    status text,
    dirty_version bigint,
    claimed_version bigint,
    attempt_count integer,
    max_attempts integer,
    next_retry_at timestamptz,
    lease_owner text,
    lease_until timestamptz,
    last_error text,
    completed_at timestamptz,
    created_at timestamptz,
    updated_at timestamptz
  );

  create table public.stock_price_history (
    symbol text references public.stock_master(symbol),
    trade_date date,
    open numeric,
    high numeric,
    low numeric,
    close numeric not null,
    volume numeric,
    trade_value numeric,
    transactions bigint,
    source text not null default 'TWSE',
    updated_at timestamptz default clock_timestamp(),
    primary key (symbol, trade_date)
  );

  create function public.twss_v20_public_stock_signals(text, text)
  returns setof public.v20_model_signals
  language sql as $$ select * from public.v20_model_signals where false $$;
  create function public.twss_v20_public_backtest_summary(text, integer, text, text, text)
  returns jsonb language sql as $$ select '{}'::jsonb $$;
  create function public.twss_v20_public_backtest_summary_v20(text, integer, text, text, text)
  returns jsonb language sql as $$ select '{}'::jsonb $$;
  create function public.twss_v20_publication_state()
  returns jsonb language sql as $$ select '{}'::jsonb $$;
`;

const seedSql = `
  insert into public.stock_master values ('2330');

  insert into public.v20_market_context (
    data_date, model_version, regime, regime_score, confidence, completeness,
    status, taiex, tpex, tx_futures, breadth, institutional, global_context,
    source_dates, degraded_sources, fetched_at
  ) values (
    current_date - 5, '20.1', 'sideways', 4.25, 75, 100, 'ready',
    '{"close":23500,"basis":"official"}',
    '{"close":275,"basis":"official"}',
    '{"settlement":23280}',
    '{"all":{"advanceRatio":52.5}}',
    '{"net":1200000}',
    '{"sp500":{"value":6300,"dataDate":"2026-07-15"}}',
    jsonb_build_object('snapshots', (current_date - 5)::text, 'global', '2026-07-15'),
    array[]::text[],
    clock_timestamp() - interval '1 minute'
  );

  insert into public.v20_universe_membership values (
    '2330', current_date - 5, '20.1', 'listed', 'TSMC', 'TWSE',
    'Semiconductor', 'stock', true, true, true, '[]', '[]',
    '{"price":"pit"}', clock_timestamp()
  );

  insert into public.v20_model_signals (
    symbol, signal_date, model_key, horizon_days, model_version,
    group_name, name, market, industry, instrument_type, strategy_key,
    opportunity_score, risk_score, confidence, completeness, official,
    gate_passed, gate_results, feature_scores, prediction_basis,
    up_probability, expected_return_net, recommended_holding_days,
    recommended_action, reasons, risks, invalidation_conditions, source_dates,
    raw_opportunity_score, net_opportunity_score, estimated_commission_pct,
    estimated_tax_pct, estimated_slippage_pct, estimated_spread_pct,
    estimated_total_cost_pct, downside_penalty_score, turnover_penalty_score,
    cost_penalty_score, turnover_exposure, liquidity_grade,
    calibration_sample_count, expected_excess_return_gross,
    expected_excess_return_net, benchmark_key, research_only, calibration_version
  )
  select
    '2330', current_date - 5, h.model_key, h.horizon_days, '20.1',
    'listed', 'TSMC', 'TWSE', 'Semiconductor', 'stock', 'baseline',
    80, 20, 75, 100, true, true, '{}', '{}', 'rules_only',
    null, 1.25, h.horizon_days, 'observe', '[]', '[]', '[]', '{"price":"pit"}',
    85, 80, 0.285, 0.3, 0.2, 0.1, 0.885, 2, 1, 2, 2, 'A',
    0, null, null, 'TAIEX', h.model_key = 'medium' and h.horizon_days = 60,
    '${calibrationVersion}'
  from (
    values
      ('short', 2), ('short', 3), ('short', 5), ('short', 10),
      ('medium', 10), ('medium', 20), ('medium', 40), ('medium', 60)
  ) h(model_key, horizon_days);
`;

async function registerRelease(modelKey, artifactHash, validationStatus = "passed") {
  const result = await db.query(
    "select public.twss_v20_register_model_release($1::jsonb) release_id",
    [JSON.stringify({
      modelKey,
      modelVersion: "20.1",
      artifactHash,
      featureVersion: "features-20.1",
      costModelVersion: "taiwan-cost-2026.1",
      calibrationVersion,
      validationStatus,
      configuration: { engine: "test-transparent-rules" },
      validationMetrics: { validationKind: "structural-test" },
      registeredBy: "pglite-test",
    })],
  );
  return Number(result.rows[0].release_id);
}

async function setChannel(modelKey, channel, releaseId) {
  return (
    await db.query(
      "select public.twss_v20_set_model_channel($1::jsonb) result",
      [JSON.stringify({
        modelKey,
        channel,
        releaseId,
        reason: "PGlite publication binding test",
        changedBy: "pglite-test",
      })],
    )
  ).rows[0].result;
}

async function setValidation(releaseId, validationStatus) {
  await db.query(
    "select public.twss_v20_record_model_validation($1::jsonb)",
    [JSON.stringify({
      releaseId,
      validationStatus,
      validationMetrics: { validationKind: "structural-test" },
      recordedBy: "pglite-test",
    })],
  );
}

async function publish(request) {
  return (
    await db.query(
      "select public.twss_v20_publish_recommendation_run($1::jsonb) result",
      [JSON.stringify(request)],
    )
  ).rows[0].result;
}

try {
  await db.exec(prerequisiteSql);
  await db.exec(await readFile(immutableMigrationUrl, "utf8"));
  await db.exec(await readFile(bindingMigrationUrl, "utf8"));
  await db.exec(seedSql);

  const dates = (
    await db.query("select (current_date - 5)::text data_date")
  ).rows[0];
  const marketContext = (
    await db.query(`
      select pg_catalog.to_jsonb(c) market_context
      from public.v20_market_context c
      where c.data_date = current_date - 5 and c.model_version = '20.1'
    `)
  ).rows[0].market_context;
  const dataCutoffAt = (
    await db.query(
      `select public.twss_v20_signal_data_cutoff(
        jsonb_build_object('dataDate', (current_date - 5)::text, 'modelVersion', '20.1')
      ) result`,
    )
  ).rows[0].result.dataCutoffAt;
  const manifests = buildV20PublicationManifests({
    dataDate: dates.data_date,
    dataCutoffAt,
    sourceDates: {
      listed: dates.data_date,
      universe: dates.data_date,
    },
    groupCounts: { listed: 1 },
    marketContext,
  });
  const request = {
    dataDate: dates.data_date,
    dataCutoffAt,
    modelVersion: "20.1",
    featureVersion: "features-20.1",
    costModelVersion: "taiwan-cost-2026.1",
    calibrationVersion,
    codeHash: artifactA,
    sourceVersion: "official-pit-v1",
    sourceHash: "1".repeat(64),
    ...manifests,
    expectedSymbolCount: 1,
    scoredSymbolCount: 1,
    cycleCompleteness: 100,
    deadletterCount: 0,
    terminalErrors: [],
    marketContext,
    marketRegime: "sideways",
  };

  const privileges = (
    await db.query(`
      select
        has_function_privilege(
          'service_role',
          'public.twss_v20_publish_recommendation_run(jsonb)',
          'EXECUTE'
        ) wrapper_allowed,
        has_function_privilege(
          'service_role',
          'public.twss_v20_publish_recommendation_run_champion_base(jsonb)',
          'EXECUTE'
        ) base_allowed
    `)
  ).rows[0];
  assert.equal(privileges.wrapper_allowed, true);
  assert.equal(privileges.base_allowed, false, "service_role must not execute the private base publisher");

  const bindingColumns = (
    await db.query(`
      select column_name, is_nullable
      from information_schema.columns
      where table_schema = 'public'
        and table_name = 'v20_recommendation_runs'
        and column_name in ('short_release_id', 'medium_release_id')
      order by column_name
    `)
  ).rows;
  assert.deepEqual(
    bindingColumns.map((column) => [column.column_name, column.is_nullable]),
    [["medium_release_id", "YES"], ["short_release_id", "YES"]],
    "release bindings stay nullable only so pre-migration immutable rows remain valid",
  );

  await assert.rejects(publish(request), /v20_short_champion_required/);

  const shortA = await registerRelease("short", artifactA);
  await setChannel("short", "champion", shortA);
  await assert.rejects(publish(request), /v20_medium_champion_required/);

  const mediumA = await registerRelease("medium", artifactA);
  await setChannel("medium", "champion", mediumA);
  await setValidation(mediumA, "failed");
  await assert.rejects(publish(request), /v20_publication_requires_passed_champions/);
  await setValidation(mediumA, "passed");

  await assert.rejects(
    publish({ ...request, modelVersion: "20.2" }),
    /v20_champion_model_version_mismatch/,
  );
  await assert.rejects(
    publish({ ...request, featureVersion: "features-other" }),
    /v20_champion_feature_version_mismatch/,
  );
  await assert.rejects(
    publish({ ...request, costModelVersion: "cost-other" }),
    /v20_champion_cost_model_version_mismatch/,
  );
  await assert.rejects(
    publish({ ...request, calibrationVersion: "calibration-other" }),
    /v20_champion_calibration_version_mismatch/,
  );
  await assert.rejects(
    publish({ ...request, codeHash: "short-hash" }),
    /v20_invalid_champion_publication_metadata/,
  );
  await assert.rejects(
    publish({ ...request, codeHash: "e".repeat(64) }),
    /v20_champion_artifact_hash_mismatch/,
  );

  const mediumC = await registerRelease("medium", artifactC);
  await setChannel("medium", "champion", mediumC);
  await assert.rejects(publish(request), /v20_champion_artifact_hash_mismatch/);
  await setChannel("medium", "champion", mediumA);

  const shortChallenger = await registerRelease("short", artifactB);
  await setChannel("short", "challenger", shortChallenger);
  const maliciousManifest = structuredClone(request.modelManifest);
  maliciousManifest.short.championRelease = {
    modelKey: "short",
    channel: "challenger",
    releaseId: shortChallenger,
    artifactHash: artifactB,
  };

  const first = await publish({ ...request, modelManifest: maliciousManifest });
  assert.equal(first.items, 8);
  assert.equal(first.shortReleaseId, shortA);
  assert.equal(first.mediumReleaseId, mediumA);
  assert.equal(first.championArtifactHash, artifactA);

  const storedFirst = (
    await db.query(`
      select short_release_id, medium_release_id, model_manifest, content_hash
      from public.v20_recommendation_runs
      where id = $1
    `, [first.runId])
  ).rows[0];
  assert.equal(Number(storedFirst.short_release_id), shortA);
  assert.equal(Number(storedFirst.medium_release_id), mediumA);
  assert.equal(storedFirst.model_manifest.publicationBindingVersion, "champion-release-v1");
  assert.equal(storedFirst.model_manifest.short.championRelease.channel, "champion");
  assert.equal(Number(storedFirst.model_manifest.short.championRelease.releaseId), shortA);
  assert.equal(Number(storedFirst.model_manifest.medium.championRelease.releaseId), mediumA);

  await assert.rejects(
    db.query(
      "select public.twss_v20_publish_recommendation_run_champion_base($1::jsonb)",
      [JSON.stringify({ ...request, codeHash: "f".repeat(64) })],
    ),
    /v20_champion_release_binding_required/,
    "the insert trigger must reject a base call without a verified binding manifest",
  );

  await db.exec("set role service_role");
  try {
    const servicePublication = await publish({ ...request, modelManifest: maliciousManifest });
    assert.equal(servicePublication.runId, first.runId);
    assert.equal(servicePublication.shortReleaseId, shortA);
    assert.equal(servicePublication.mediumReleaseId, mediumA);
    await assert.rejects(
      db.query(
        "select public.twss_v20_publish_recommendation_run_champion_base($1::jsonb)",
        [JSON.stringify(request)],
      ),
      /permission denied/i,
    );
  } finally {
    await db.exec("reset role");
  }

  const shortD = await registerRelease("short", artifactD);
  const mediumD = await registerRelease("medium", artifactD);
  await setChannel("short", "champion", shortD);
  await setChannel("medium", "champion", mediumD);

  const second = await publish({
    ...request,
    codeHash: artifactD,
  });
  assert.equal(second.shortReleaseId, shortD);
  assert.equal(second.mediumReleaseId, mediumD);
  assert.notEqual(
    second.contentHash,
    first.contentHash,
    "promoting a new Champion pair must produce a different immutable content hash for unchanged signals",
  );

  const storedSecond = (
    await db.query(`
      select short_release_id, medium_release_id, model_manifest
      from public.v20_recommendation_runs
      where id = $1
    `, [second.runId])
  ).rows[0];
  assert.equal(Number(storedSecond.short_release_id), shortD);
  assert.equal(Number(storedSecond.medium_release_id), mediumD);
  assert.notDeepEqual(
    storedSecond.model_manifest.short.championRelease,
    storedFirst.model_manifest.short.championRelease,
  );
  assert.notDeepEqual(
    storedSecond.model_manifest.medium.championRelease,
    storedFirst.model_manifest.medium.championRelease,
  );

  console.log("v20 Champion publication binding SQL test passed");
} finally {
  await db.close();
}

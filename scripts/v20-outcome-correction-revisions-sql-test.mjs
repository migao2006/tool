import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { PGlite } from "@electric-sql/pglite";
import { pgcrypto } from "@electric-sql/pglite/contrib/pgcrypto";

const migrationUrl = new URL(
  "../supabase/migrations/20260716183000_add_v20_outcome_correction_revisions.sql",
  import.meta.url,
);
const baseMigrationUrl = new URL(
  "../supabase/migrations/20260716173332_verifiable_opportunity_snapshots.sql",
  import.meta.url,
);
const calibrationMigrationUrl = new URL(
  "../supabase/migrations/20260716182335_add_v20_immutable_calibration_snapshots.sql",
  import.meta.url,
);

const [sql, baseSql, calibrationSql] = await Promise.all([
  readFile(migrationUrl, "utf8"),
  readFile(baseMigrationUrl, "utf8"),
  readFile(calibrationMigrationUrl, "utf8"),
]);

assert.match(sql, /v_evaluation_cutoff timestamptz := clock_timestamp\(\)/i);
assert.ok(
  (sql.match(/updated_at <= v_evaluation_cutoff/gi) ?? []).length >= 3,
  "every maturity, change-detection, and evaluation price read must share the fixed cutoff",
);
assert.match(sql, /twss-v20-immutable-outcomes-global/i);
assert.match(sql, /twss-v20-outcome:'[\s\S]+recommendation_item_id/i);
assert.match(
  baseSql,
  /twss-v20-outcome:'[\s\S]+v_item_id[\s\S]+v_horizon_days/i,
  "the automatic evaluator must retain the manual append RPC's per-item lock key",
);
assert.match(sql, /latest_observations[\s\S]+order by[\s\S]+o\.revision desc[\s\S]+o\.id desc/i);
assert.match(sql, /previousObservation/i);
assert.match(sql, /previousObservationHash/i);
assert.match(sql, /correctionReason/i);
assert.doesNotMatch(
  sql,
  /pg_catalog\.(?:coalesce|nullif|greatest|least)\s*\(/i,
  "Postgres special forms cannot be schema-qualified on hosted Supabase",
);
assert.doesNotMatch(
  sql,
  /(?:update|delete\s+from)\s+public\.v20_outcome_observations/i,
  "corrections must append and never mutate old outcomes",
);

// Both downstream consumers already select the latest immutable revision.
assert.match(
  baseSql,
  /twss_v20_read_validation_summary[\s\S]+partition by o\.recommendation_item_id, o\.observed_horizon_days[\s\S]+order by o\.revision desc/i,
);
assert.match(
  calibrationSql,
  /latest_revisions as materialized[\s\S]+partition by o\.recommendation_item_id, o\.observed_horizon_days[\s\S]+order by o\.revision desc, o\.id desc/i,
);

const db = new PGlite({ extensions: { pgcrypto } });

try {
  await db.exec(`
    create role anon;
    create role authenticated;
    create role service_role bypassrls;
    create schema extensions;
    create extension pgcrypto with schema extensions;

    create table public.v20_recommendation_runs (
      id bigint generated always as identity primary key,
      status text not null
    );

    create table public.v20_recommendation_items (
      id bigint generated always as identity primary key,
      run_id bigint not null references public.v20_recommendation_runs(id),
      symbol text not null,
      signal_date date not null,
      model_key text not null,
      horizon_days integer not null,
      group_name text not null,
      industry text,
      public_visible boolean not null,
      is_eligible boolean not null,
      estimated_total_cost_pct numeric not null,
      input_hash text not null,
      take_profit_1 numeric,
      stop_loss numeric
    );

    create table public.stock_price_history (
      symbol text not null,
      trade_date date not null,
      open numeric,
      high numeric,
      low numeric,
      close numeric not null,
      source text not null,
      updated_at timestamptz not null,
      primary key (symbol, trade_date)
    );

    create table public.v20_outcome_observations (
      id bigint generated always as identity primary key,
      recommendation_item_id bigint not null
        references public.v20_recommendation_items(id),
      observed_horizon_days integer not null,
      revision integer not null,
      entry_date date not null,
      entry_price numeric not null,
      exit_date date not null,
      exit_price numeric not null,
      gross_return numeric not null,
      transaction_cost numeric not null,
      net_return numeric not null,
      benchmark_key text not null,
      benchmark_return numeric not null,
      industry_benchmark_key text,
      industry_return numeric,
      excess_return_net numeric not null,
      industry_excess_return_net numeric,
      mfe numeric,
      mae numeric,
      target_hit_first boolean,
      source_version text not null,
      source_hash text not null,
      source_manifest jsonb not null,
      calibration_run_key text,
      observation_hash text not null unique,
      observed_at timestamptz not null,
      recorded_at timestamptz not null,
      unique (recommendation_item_id, observed_horizon_days, revision)
    );

    create or replace function public.twss_v20_reject_immutable_change()
    returns trigger
    language plpgsql
    set search_path = ''
    as $$
    begin
      raise exception 'v20_immutable_record' using errcode = '55000';
    end;
    $$;

    create trigger v20_immutable_v20_outcome_observations
    before update or delete on public.v20_outcome_observations
    for each row execute function public.twss_v20_reject_immutable_change();
  `);

  await db.exec(sql);

  await db.exec(`
    insert into public.v20_recommendation_runs (status) values ('published');

    insert into public.v20_recommendation_items (
      run_id, symbol, signal_date, model_key, horizon_days, group_name,
      industry, public_visible, is_eligible, estimated_total_cost_pct,
      input_hash, take_profit_1, stop_loss
    )
    select
      1,
      (1000 + g)::text,
      current_date - 5,
      'short',
      2,
      'listed',
      'semiconductor',
      true,
      true,
      0.9,
      pg_catalog.encode(extensions.digest('item-' || g::text, 'sha256'), 'hex'),
      150,
      50
    from generate_series(1, 5) g;

    insert into public.stock_price_history (
      symbol, trade_date, open, high, low, close, source, updated_at
    )
    select
      (1000 + stock)::text,
      current_date - session.offset_days,
      100 + stock + session.session_number,
      103 + stock + session.session_number,
      99 + stock + session.session_number,
      101 + stock + session.session_number,
      'TWSE',
      clock_timestamp() - interval '1 day'
    from generate_series(1, 5) stock
    cross join (values (4, 1), (3, 2), (2, 3)) session(offset_days, session_number);
  `);

  const asOfDate = (
    await db.query("select (current_date - 3)::text as_of_date")
  ).rows[0].as_of_date;

  const privileges = (
    await db.query(`
      select
        has_function_privilege(
          'anon',
          'public.twss_v20_evaluate_immutable_outcomes(date,integer)',
          'execute'
        ) anon_execute,
        has_function_privilege(
          'service_role',
          'public.twss_v20_evaluate_immutable_outcomes(date,integer)',
          'execute'
        ) service_execute
    `)
  ).rows[0];
  assert.deepEqual(privileges, { anon_execute: false, service_execute: true });

  await db.exec("set role service_role");
  const first = (
    await db.query(
      "select public.twss_v20_evaluate_immutable_outcomes($1::date, 100) result",
      [asOfDate],
    )
  ).rows[0].result;
  await db.exec("reset role");
  assert.equal(first.inserted, 5);
  assert.equal(first.initialObservations, 5);
  assert.equal(first.revisions, 0);

  const initial = (
    await db.query(`
      select o.observation_hash, o.source_hash
      from public.v20_outcome_observations o
      join public.v20_recommendation_items i on i.id = o.recommendation_item_id
      where i.symbol = '1001' and o.revision = 1
    `)
  ).rows[0];

  // A row newer than the invocation cutoff must not leak into evaluation.
  await db.exec(`
    update public.stock_price_history
    set open = 999,
        updated_at = clock_timestamp() + interval '1 day'
    where symbol = '1001' and trade_date = current_date - 4;
  `);
  const futureDated = (
    await db.query(
      "select public.twss_v20_evaluate_immutable_outcomes($1::date, 100) result",
      [asOfDate],
    )
  ).rows[0].result;
  assert.equal(futureDated.inserted, 0);

  // Correct the target's first-session open. The target path and the equal-
  // weight peer benchmark both change, so all five latest outcomes become rev 2.
  await db.exec(`
    update public.stock_price_history
    set open = 90,
        updated_at = clock_timestamp()
    where symbol = '1001' and trade_date = current_date - 4;
  `);
  const targetCorrection = (
    await db.query(
      "select public.twss_v20_evaluate_immutable_outcomes($1::date, 100) result",
      [asOfDate],
    )
  ).rows[0].result;
  assert.equal(targetCorrection.inserted, 5);
  assert.equal(targetCorrection.revisions, 5);

  const targetRevision = (
    await db.query(`
      select
        o.revision,
        o.observation_hash,
        o.source_manifest,
        o.entry_price
      from public.v20_outcome_observations o
      join public.v20_recommendation_items i on i.id = o.recommendation_item_id
      where i.symbol = '1001'
      order by o.revision desc
      limit 1
    `)
  ).rows[0];
  assert.equal(targetRevision.revision, 2);
  assert.equal(Number(targetRevision.entry_price), 90);
  assert.match(targetRevision.source_manifest.correctionReason, /target_price_history_revised/);
  assert.equal(
    targetRevision.source_manifest.previousObservation.observationHash,
    initial.observation_hash,
  );
  assert.equal(targetRevision.source_manifest.previousSourceHash, initial.source_hash);

  const fixedCutoff = (
    await db.query(`
      select
        count(distinct source_manifest ->> 'evaluationCutoffAt')::integer cutoff_count,
        bool_and(
          (source_manifest ->> 'priceMaxUpdatedAt')::timestamptz
            <= (source_manifest ->> 'evaluationCutoffAt')::timestamptz
        ) sources_before_cutoff
      from public.v20_outcome_observations
      where revision = 2
    `)
  ).rows[0];
  assert.deepEqual(fixedCutoff, { cutoff_count: 1, sources_before_cutoff: true });

  // Correct only a same-group peer. The target's own path stays unchanged, but
  // its benchmark hash and latest outcome must advance to revision 3.
  await db.exec(`
    update public.stock_price_history
    set close = close + 12,
        high = high + 12,
        updated_at = clock_timestamp()
    where symbol = '1002' and trade_date = current_date - 3;
  `);
  const peerCorrection = (
    await db.query(
      "select public.twss_v20_evaluate_immutable_outcomes($1::date, 100) result",
      [asOfDate],
    )
  ).rows[0].result;
  assert.equal(peerCorrection.inserted, 5);
  assert.equal(peerCorrection.revisions, 5);

  const peerDrivenTargetRevision = (
    await db.query(`
      select o.revision, o.source_manifest
      from public.v20_outcome_observations o
      join public.v20_recommendation_items i on i.id = o.recommendation_item_id
      where i.symbol = '1001'
      order by o.revision desc
      limit 1
    `)
  ).rows[0];
  assert.equal(peerDrivenTargetRevision.revision, 3);
  assert.match(
    peerDrivenTargetRevision.source_manifest.correctionReason,
    /group_peer_benchmark_revised/,
  );
  assert.doesNotMatch(
    peerDrivenTargetRevision.source_manifest.correctionReason,
    /target_price_history_revised/,
  );

  // The third session is beyond the 2-day holding path and beyond p_as_of_date.
  // Its correction cannot create a new 2-day observation revision.
  await db.exec(`
    update public.stock_price_history
    set close = close + 50,
        high = high + 50,
        updated_at = clock_timestamp()
    where symbol = '1003' and trade_date = current_date - 2;
  `);
  const afterHorizon = (
    await db.query(
      "select public.twss_v20_evaluate_immutable_outcomes($1::date, 100) result",
      [asOfDate],
    )
  ).rows[0].result;
  const identicalRerun = (
    await db.query(
      "select public.twss_v20_evaluate_immutable_outcomes($1::date, 100) result",
      [asOfDate],
    )
  ).rows[0].result;
  assert.equal(afterHorizon.inserted, 0);
  assert.equal(identicalRerun.inserted, 0);

  const history = (
    await db.query(`
      select
        count(*)::integer observations,
        count(distinct recommendation_item_id)::integer items,
        min(revision)::integer min_revision,
        max(revision)::integer max_revision
      from public.v20_outcome_observations
    `)
  ).rows[0];
  assert.deepEqual(history, {
    observations: 15,
    items: 5,
    min_revision: 1,
    max_revision: 3,
  });

  const preservedInitial = (
    await db.query(`
      select observation_hash, source_hash
      from public.v20_outcome_observations o
      join public.v20_recommendation_items i on i.id = o.recommendation_item_id
      where i.symbol = '1001' and o.revision = 1
    `)
  ).rows[0];
  assert.deepEqual(preservedInitial, initial);
  await assert.rejects(
    db.exec("update public.v20_outcome_observations set net_return = 0 where revision = 1"),
    /v20_immutable_record/,
  );

  console.log("v20 outcome correction revision SQL checks passed", {
    initial: first.inserted,
    targetRevisions: targetCorrection.revisions,
    peerRevisions: peerCorrection.revisions,
    observations: history.observations,
  });
} finally {
  await db.close();
}

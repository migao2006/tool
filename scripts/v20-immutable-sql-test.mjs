import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { PGlite } from "@electric-sql/pglite";
import { pgcrypto } from "@electric-sql/pglite/contrib/pgcrypto";
import { buildV20PublicationManifests } from "../supabase/functions/_shared/v20-publication-contract.js";
import { V20_MODEL_ARTIFACT_HASH } from "../supabase/functions/_shared/v20-model-artifact.js";

const migrationUrl = new URL(
  "../supabase/migrations/20260716173332_verifiable_opportunity_snapshots.sql",
  import.meta.url,
);
const pointInTimeValidationMigrationUrl = new URL(
  "../supabase/migrations/20260716185000_fix_v20_point_in_time_validation_summary.sql",
  import.meta.url,
);
const publicReadRpcMigrationUrl = new URL(
  "../supabase/migrations/20260716190000_enable_v20_public_read_rpc.sql",
  import.meta.url,
);

const db = new PGlite({ extensions: { pgcrypto } });
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
  insert into public.stock_master
  select (1000 + value)::text from generate_series(1, 5) value;

  insert into public.v20_market_context (
    data_date, model_version, regime, regime_score, confidence, completeness,
    status, taiex, tpex, tx_futures, breadth, institutional, global_context,
    source_dates, degraded_sources, fetched_at
  ) values (
    current_date - 5, '20.1', 'sideways', 4.25, 75, 75, 'partial',
    '{"close":23500,"basis":"official"}',
    '{"close":275,"basis":"official"}',
    '{"settlement":23280}',
    '{"all":{"advanceRatio":52.5}}',
    '{"net":1200000}',
    '{"sp500":{"value":6300,"dataDate":"2026-07-15"}}',
    jsonb_build_object('snapshots', (current_date - 5)::text, 'global', '2026-07-15'),
    array['tx_futures_delayed'],
    clock_timestamp() - interval '1 minute'
  );

  insert into public.v20_universe_membership
  select
    symbol,
    current_date - 5,
    '20.1',
    'listed',
    'Stock ' || symbol,
    'TWSE',
    '半導體',
    'stock',
    true,
    true,
    true,
    '[]',
    '[]',
    '{"price":"pit"}',
    clock_timestamp()
  from public.stock_master;

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
    expected_excess_return_net, benchmark_key, research_only
  )
  select
    stock.symbol,
    current_date - 5,
    horizon.model_key,
    horizon.horizon_days,
    '20.1',
    'listed',
    'Stock ' || stock.symbol,
    'TWSE',
    '半導體',
    'stock',
    'baseline',
    80,
    20,
    75,
    100,
    true,
    true,
    '{}',
    '{}',
    'rules_only',
    null,
    1.25,
    horizon.horizon_days,
    'observe',
    '[]',
    '[]',
    '[]',
    '{"price":"pit"}',
    85,
    80,
    0.285,
    0.3,
    0.2,
    0.1,
    0.885,
    2,
    1,
    2,
    2,
    'A',
    0,
    null,
    null,
    'TAIEX',
    horizon.model_key = 'medium' and horizon.horizon_days = 60
  from public.stock_master stock
  cross join (
    values
      ('short', 2), ('short', 3), ('short', 5), ('short', 10),
      ('medium', 10), ('medium', 20), ('medium', 40), ('medium', 60)
  ) horizon(model_key, horizon_days);

  insert into public.stock_price_history (
    symbol, trade_date, open, high, low, close, source
  )
  select
    stock.symbol,
    current_date - offset_days,
    100 + offset_days,
    102 + offset_days,
    99 + offset_days,
    101 + offset_days,
    'TWSE'
  from public.stock_master stock
  cross join generate_series(4, 0, -1) offset_days;
`;

try {
  await db.exec(prerequisiteSql);
  await db.exec(await readFile(migrationUrl, "utf8"));
  await db.exec(await readFile(pointInTimeValidationMigrationUrl, "utf8"));
  await db.exec(await readFile(publicReadRpcMigrationUrl, "utf8"));
  await db.exec(seedSql);

  const dates = (
    await db.query("select (current_date - 5)::text data_date, current_date::text as_of_date")
  ).rows[0];

  const cutoffResult = (
    await db.query(
      `select public.twss_v20_signal_data_cutoff(
        jsonb_build_object('dataDate', (current_date - 5)::text, 'modelVersion', '20.1')
      ) result`,
    )
  ).rows[0].result;
  let dataCutoffAt = cutoffResult.dataCutoffAt;
  assert.equal(cutoffResult.signalCount, 40);
  await assert.rejects(
    db.query(
      `select public.twss_v20_signal_data_cutoff(
        jsonb_build_object('dataDate', (current_date + 30)::text, 'modelVersion', '20.1')
      )`,
    ),
    /v20_signal_data_cutoff_unavailable/,
    "an empty staging cycle must not manufacture a publication cutoff",
  );
  const marketContext = (
    await db.query(`
      select pg_catalog.to_jsonb(c) market_context
      from public.v20_market_context c
      where c.data_date = current_date - 5 and c.model_version = '20.1'
    `)
  ).rows[0].market_context;
  const manifests = buildV20PublicationManifests({
    dataDate: dates.data_date,
    dataCutoffAt,
    sourceDates: { listed: dates.data_date, otc: dates.data_date, etf: dates.data_date, universe: dates.data_date },
    groupCounts: { listed: 5, otc: 0, etf: 0 },
    marketContext,
  });
  const request = {
    dataDate: dates.data_date,
    dataCutoffAt,
    modelVersion: "20.1",
    featureVersion: "features-20.1",
    costModelVersion: "taiwan-cost-2026.1",
    codeHash: V20_MODEL_ARTIFACT_HASH,
    sourceVersion: "official-pit-v1",
    sourceHash: "a".repeat(64),
    ...manifests,
    expectedSymbolCount: 5,
    scoredSymbolCount: 5,
    cycleCompleteness: 100,
    deadletterCount: 0,
    terminalErrors: [],
    marketContext,
    marketRegime: "sideways",
  };

  // A staging update between the worker's cutoff read and the atomic
  // publisher must reject the stale request rather than silently copying a
  // different signal set under the old source manifest.
  await db.exec(`
    update public.v20_model_signals
    set updated_at = updated_at + interval '1 second'
    where symbol = '1001' and model_key = 'short' and horizon_days = 2;
  `);
  await assert.rejects(
    db.query(
      "select public.twss_v20_publish_recommendation_run($1::jsonb)",
      [JSON.stringify(request)],
    ),
    /v20_signal_data_cutoff_changed/,
    "a staging write after cutoff discovery must abort the publication transaction",
  );
  dataCutoffAt = (
    await db.query(
      `select public.twss_v20_signal_data_cutoff(
        jsonb_build_object('dataDate', (current_date - 5)::text, 'modelVersion', '20.1')
      ) result`,
    )
  ).rows[0].result.dataCutoffAt;
  const refreshedManifests = buildV20PublicationManifests({
    dataDate: dates.data_date,
    dataCutoffAt,
    sourceDates: { listed: dates.data_date, otc: dates.data_date, etf: dates.data_date, universe: dates.data_date },
    groupCounts: { listed: 5, otc: 0, etf: 0 },
    marketContext,
  });
  Object.assign(request, refreshedManifests, { dataCutoffAt });

  await assert.rejects(
    db.query(
      "select public.twss_v20_publish_recommendation_run($1::jsonb)",
      [JSON.stringify({
        ...request,
        marketContext: { ...marketContext, confidence: Number(marketContext.confidence) - 1 },
      })],
    ),
    /v20_market_context_mismatch/,
    "the publisher must reject a context that differs from the locked authoritative row",
  );

  await db.exec(`
    update public.v20_model_signals
    set calibration_version = 'twss-cal-sha256-' || repeat('a', 64)
    where symbol = '1001' and model_key = 'short' and horizon_days = 2;
  `);
  await assert.rejects(
    db.query(
      "select public.twss_v20_publish_recommendation_run($1::jsonb)",
      [JSON.stringify(request)],
    ),
    /v20_calibration_version_mismatch/,
    "a publication cannot claim a calibration snapshot different from its scored staging rows",
  );
  await db.exec(`
    update public.v20_model_signals
    set calibration_version = null
    where symbol = '1001' and model_key = 'short' and horizon_days = 2;
  `);

  await db.exec(`
    insert into public.v20_model_dirty_queue (
      symbol, data_date, group_name, model_version, status,
      dirty_version, claimed_version, attempt_count, max_attempts
    ) values (
      '1001', current_date - 5, 'listed', '20.1', 'pending',
      1, null, 0, 5
    );
  `);
  await assert.rejects(
    db.query(
      "select public.twss_v20_publish_recommendation_run($1::jsonb)",
      [JSON.stringify(request)],
    ),
    /v20_dirty_queue_not_settled/,
  );
  await db.exec("delete from public.v20_model_dirty_queue");

  const publication = (
    await db.query(
      "select public.twss_v20_publish_recommendation_run($1::jsonb) result",
      [JSON.stringify(request)],
    )
  ).rows[0].result;
  assert.equal(publication.items, 40);
  assert.equal(publication.publicItems, 35);
  assert.equal(publication.researchItems, 5);
  assert.equal(publication.idempotent, false);

  const storedMarketContext = (
    await db.query(
      "select market_context_snapshot from public.v20_recommendation_runs where id = $1",
      [publication.runId],
    )
  ).rows[0].market_context_snapshot;
  assert.deepEqual(storedMarketContext, marketContext);
  const storedExpectedReturn = (
    await db.query(`
      select expected_return_net
      from public.v20_recommendation_items
      where run_id = $1 and symbol = '1001' and model_key = 'short' and horizon_days = 2
    `, [publication.runId])
  ).rows[0].expected_return_net;
  assert.equal(Number(storedExpectedReturn), 1.25,
    "the immutable item must preserve expected return separately from excess return");

  const repeatedPublication = (
    await db.query(
      "select public.twss_v20_publish_recommendation_run($1::jsonb) result",
      [JSON.stringify(request)],
    )
  ).rows[0].result;
  assert.equal(repeatedPublication.runId, publication.runId);
  assert.equal(repeatedPublication.idempotent, true);
  assert.equal(repeatedPublication.headChanged, false);

  const counts = (
    await db.query(`
      select
        (select count(*) from public.v20_recommendation_runs)::integer runs,
        (select count(*) from public.v20_recommendation_items)::integer items,
        (select count(*) from public.v20_recommendation_items where public_visible)::integer public_items,
        (select count(*) from public.v20_recommendation_items where research_only)::integer research_items
    `)
  ).rows[0];
  assert.deepEqual(counts, { runs: 1, items: 40, public_items: 35, research_items: 5 });

  const firstEvaluation = (
    await db.query(
      "select public.twss_v20_evaluate_immutable_outcomes($1::date, 500) result",
      [dates.as_of_date],
    )
  ).rows[0].result;
  const repeatedEvaluation = (
    await db.query(
      "select public.twss_v20_evaluate_immutable_outcomes($1::date, 500) result",
      [dates.as_of_date],
    )
  ).rows[0].result;
  assert.equal(firstEvaluation.inserted, 15);
  assert.equal(repeatedEvaluation.inserted, 0);

  // Keep publication runtime small while still executing the >=100-sample
  // validation and cohort-drawdown branch with distinct immutable items.
  await db.exec(`
    insert into public.stock_master
    select (1000 + value)::text from generate_series(6, 100) value;

    do $fixture$
    declare
      v_columns text;
      v_expressions text;
    begin
      select
        string_agg(pg_catalog.format('%I', a.attname), ', ' order by a.attnum),
        string_agg(
          case a.attname
            when 'symbol' then 's.symbol'
            when 'name' then '(''Synthetic '' || s.symbol)'
            when 'rank_position' then 's.rank_position'
            when 'previous_rank' then 'null'
            when 'rank_delta' then 'null'
            when 'market_percentile' then '(101 - s.rank_position)::numeric'
            when 'input_hash' then 'pg_catalog.encode(extensions.digest(''input-'' || s.symbol, ''sha256''), ''hex'')'
            when 'recorded_at' then 'pg_catalog.clock_timestamp()'
            else pg_catalog.format('b.%I', a.attname)
          end,
          ', ' order by a.attnum
        )
      into v_columns, v_expressions
      from pg_catalog.pg_attribute a
      where a.attrelid = 'public.v20_recommendation_items'::regclass
        and a.attnum > 0
        and not a.attisdropped
        and a.attname <> 'id';

      execute pg_catalog.format(
        'insert into public.v20_recommendation_items (%s)
         select %s
         from (
           select (1000 + value)::text symbol, value::integer rank_position
           from generate_series(6, 100) value
         ) s
         cross join (
           select * from public.v20_recommendation_items
           where symbol = ''1001'' and model_key = ''short'' and horizon_days = 2
           limit 1
         ) b',
        v_columns,
        v_expressions
      );
    end
    $fixture$;

    do $fixture$
    declare
      v_columns text;
      v_expressions text;
    begin
      select
        string_agg(pg_catalog.format('%I', a.attname), ', ' order by a.attnum),
        string_agg(
          case a.attname
            when 'recommendation_item_id' then 'i.id'
            when 'gross_return' then 'case when pg_catalog.mod(i.id, 4) = 0 then -2.1 else 1.9 end'
            when 'net_return' then 'case when pg_catalog.mod(i.id, 4) = 0 then -3 else 1 end'
            when 'benchmark_return' then '0.2'
            when 'industry_return' then '0.1'
            when 'excess_return_net' then 'case when pg_catalog.mod(i.id, 4) = 0 then -3.2 else 0.8 end'
            when 'industry_excess_return_net' then 'case when pg_catalog.mod(i.id, 4) = 0 then -3.1 else 0.9 end'
            when 'mfe' then '2'
            when 'mae' then 'case when pg_catalog.mod(i.id, 4) = 0 then -4 else -0.5 end'
            when 'observation_hash' then 'pg_catalog.encode(extensions.digest(''outcome-'' || i.id::text, ''sha256''), ''hex'')'
            when 'observed_at' then 'pg_catalog.clock_timestamp()'
            when 'recorded_at' then 'pg_catalog.clock_timestamp()'
            else pg_catalog.format('b.%I', a.attname)
          end,
          ', ' order by a.attnum
        )
      into v_columns, v_expressions
      from pg_catalog.pg_attribute a
      where a.attrelid = 'public.v20_outcome_observations'::regclass
        and a.attnum > 0
        and not a.attisdropped
        and a.attname <> 'id';

      execute pg_catalog.format(
        'insert into public.v20_outcome_observations (%s)
         select %s
         from public.v20_recommendation_items i
         cross join (
           select o.*
           from public.v20_outcome_observations o
           join public.v20_recommendation_items source_item
             on source_item.id = o.recommendation_item_id
           where source_item.symbol = ''1001''
             and source_item.model_key = ''short''
             and source_item.horizon_days = 2
           limit 1
         ) b
         where i.model_key = ''short''
           and i.horizon_days = 2
           and i.symbol >= ''1006''',
        v_columns,
        v_expressions
      );
    end
    $fixture$;
  `);

  const rankings = (
    await db.query(`
      select public.twss_v20_read_rankings(
        '{"modelKey":"short","horizonDays":2,"limit":3}'::jsonb
      ) result
    `)
  ).rows[0].result;
  assert.equal(rankings.total, 100);
  assert.equal(rankings.pageCount, 3);
  assert.equal(rankings.hasMore, true);
  assert.equal(rankings.items.length, 3);

  const stock = (
    await db.query(`
      select public.twss_v20_read_stock_snapshot('{"symbol":"1001"}'::jsonb) result
    `)
  ).rows[0].result;
  assert.equal(stock.found, true);
  assert.equal(stock.items.length, 7);
  assert.equal(stock.items.some((item) => item.horizonDays === 60), false);

  const latePublicationValidation = (
    await db.query(`
      select public.twss_v20_read_validation_summary(
        '{"modelKey":"short","horizonDays":2,"topN":100}'::jsonb
      ) result
    `)
  ).rows[0].result;
  assert.equal(latePublicationValidation.status, "insufficient_data");
  assert.equal(latePublicationValidation.sampleCount, 0,
    "a run published after its observed entry session must never enter validation");

  // The publisher fixture deliberately backfills an old data date at the
  // current clock. Move only the immutable run timestamp in this test fixture
  // so the positive branch represents a genuinely pre-entry publication.
  await db.exec(`
    alter table public.v20_recommendation_runs
      disable trigger v20_immutable_v20_recommendation_runs;
    update public.v20_recommendation_runs
    set published_at = pg_catalog.timezone(
      'Asia/Taipei',
      (current_date - 4)::timestamp
    ) - interval '1 hour'
    where id = ${Number(publication.runId)};
    alter table public.v20_recommendation_runs
      enable trigger v20_immutable_v20_recommendation_runs;
  `);

  const validation = (
    await db.query(`
      select public.twss_v20_read_validation_summary(
        '{"modelKey":"short","horizonDays":2,"topN":100}'::jsonb
      ) result
    `)
  ).rows[0].result;
  assert.equal(validation.status, "ready");
  assert.equal(validation.sampleCount, 100);
  assert.equal(validation.items.length, 1);
  assert.equal(typeof validation.items[0].averageExcessReturnNet, "number");
  assert.equal(typeof validation.items[0].maxRealizedCohortDrawdown, "number");

  const insufficientValidation = (
    await db.query(`
      select public.twss_v20_read_validation_summary(
        '{"modelKey":"short","horizonDays":2,"topN":100,"strategyKey":"not-present"}'::jsonb
      ) result
    `)
  ).rows[0].result;
  assert.equal(insufficientValidation.status, "insufficient_data");
  assert.equal(insufficientValidation.sampleCount, 0);
  assert.deepEqual(insufficientValidation.items, []);

  const privileges = (
    await db.query(`
      select
        has_table_privilege('anon', 'public.v20_model_signals', 'select') raw_select,
        has_function_privilege(
          'anon', 'public.twss_v20_public_stock_signals(text,text)', 'execute'
        ) raw_rpc,
        has_function_privilege(
          'service_role', 'public.twss_v20_read_rankings(jsonb)', 'execute'
        ) service_read,
        has_function_privilege(
          'anon', 'public.twss_v20_read_publication_state()', 'execute'
        ) anon_publication_read,
        has_function_privilege(
          'anon', 'public.twss_v20_read_rankings(jsonb)', 'execute'
        ) anon_ranking_read,
        has_function_privilege(
          'authenticated', 'public.twss_v20_read_stock_snapshot(jsonb)', 'execute'
        ) authenticated_stock_read,
        has_function_privilege(
          'authenticated', 'public.twss_v20_read_validation_summary(jsonb)', 'execute'
        ) authenticated_validation_read,
        has_function_privilege(
          'anon', 'public.twss_v20_signal_data_cutoff(jsonb)', 'execute'
        ) public_cutoff,
        has_function_privilege(
          'service_role', 'public.twss_v20_signal_data_cutoff(jsonb)', 'execute'
        ) service_cutoff
    `)
  ).rows[0];
  assert.deepEqual(privileges, {
    raw_select: false,
    raw_rpc: false,
    service_read: true,
    anon_publication_read: true,
    anon_ranking_read: true,
    authenticated_stock_read: true,
    authenticated_validation_read: true,
    public_cutoff: false,
    service_cutoff: true,
  });

  const publicReadDefinitions = (
    await db.query(`
      select
        pg_catalog.bool_and(p.prosecdef) security_definer,
        pg_catalog.bool_and(
          pg_catalog.array_to_string(coalesce(p.proconfig, '{}'::text[]), ',')
            in ('search_path=', 'search_path=""')
        ) empty_search_path
      from pg_catalog.pg_proc p
      where p.oid in (
        'public.twss_v20_read_publication_state()'::regprocedure,
        'public.twss_v20_read_rankings(jsonb)'::regprocedure,
        'public.twss_v20_read_stock_snapshot(jsonb)'::regprocedure,
        'public.twss_v20_read_validation_summary(jsonb)'::regprocedure
      )
    `)
  ).rows[0];
  assert.deepEqual(publicReadDefinitions, {
    security_definer: true,
    empty_search_path: true,
  });

  await db.exec("set role anon");
  const anonPublicationState = (
    await db.query("select public.twss_v20_read_publication_state() result")
  ).rows[0].result;
  const anonRankings = (
    await db.query(`
      select public.twss_v20_read_rankings(
        '{"modelKey":"short","horizonDays":2,"limit":2}'::jsonb
      ) result
    `)
  ).rows[0].result;
  const anonStock = (
    await db.query(`
      select public.twss_v20_read_stock_snapshot('{"symbol":"1001"}'::jsonb) result
    `)
  ).rows[0].result;
  const anonValidation = (
    await db.query(`
      select public.twss_v20_read_validation_summary(
        '{"modelKey":"short","horizonDays":2,"topN":100}'::jsonb
      ) result
    `)
  ).rows[0].result;
  await assert.rejects(
    db.query(`select public.twss_v20_read_rankings(
      '{"modelKey":"medium","horizonDays":60}'::jsonb
    )`),
    /v20_research_horizon_not_public/,
  );
  await db.exec("reset role");
  assert.equal(anonPublicationState.runId, publication.runId);
  assert.equal(anonRankings.items.length, 2);
  assert.equal(anonRankings.items.every((item) => item.horizonDays !== 60), true);
  assert.equal(anonStock.items.length, 7);
  assert.equal(anonStock.items.every((item) => item.horizonDays !== 60), true);
  assert.equal(anonValidation.status, "ready");

  await db.exec("set role service_role");
  const servicePublicationState = (
    await db.query("select public.twss_v20_read_publication_state() result")
  ).rows[0].result;
  const serviceRankings = (
    await db.query(`
      select public.twss_v20_read_rankings(
        '{"modelKey":"short","horizonDays":2,"limit":2}'::jsonb
      ) result
    `)
  ).rows[0].result;
  await db.exec("reset role");
  assert.equal(servicePublicationState.runId, publication.runId);
  assert.deepEqual(servicePublicationState.marketContext, marketContext);
  assert.equal(serviceRankings.items.length, 2);

  await assert.rejects(
    db.exec("update public.v20_recommendation_items set name = 'tampered'"),
    /v20_immutable_record/,
  );
  await assert.rejects(
    db.query(
      "select public.twss_v20_publish_recommendation_run($1::jsonb)",
      [JSON.stringify({ ...request, deadletterCount: 1 })],
    ),
    /v20_unpublishable_cycle_metadata/,
  );
  await assert.rejects(
    db.query(
      `select public.twss_v20_read_rankings(
        '{"modelKey":"medium","horizonDays":60}'::jsonb
      )`,
    ),
    /v20_research_horizon_not_public/,
  );

  await db.query(
    "select public.twss_v20_register_model_release($1::jsonb)",
    [JSON.stringify({
      modelKey: "short",
      modelVersion: "20.1-shadow",
      artifactHash: "1234567",
      featureVersion: "features-20.1",
      costModelVersion: "taiwan-cost-2026.1",
      validationStatus: "shadow",
    })],
  );
  const releaseId = (
    await db.query("select id from public.v20_model_releases limit 1")
  ).rows[0].id;
  await db.query(
    "select public.twss_v20_set_model_channel($1::jsonb)",
    [JSON.stringify({
      modelKey: "short",
      channel: "challenger",
      releaseId,
      reason: "shadow evaluation",
    })],
  );
  await db.query(
    "select public.twss_v20_record_model_validation($1::jsonb)",
    [JSON.stringify({
      releaseId,
      validationStatus: "passed",
      validationMetrics: { sampleCount: 100 },
    })],
  );
  await db.query(
    "select public.twss_v20_promote_challenger($1::jsonb)",
    [JSON.stringify({ modelKey: "short", reason: "sample-out validation passed" })],
  );
  const channels = await db.query("select * from public.twss_v20_read_model_channels()");
  assert.equal(channels.rows.length, 1);
  assert.equal(channels.rows[0].channel, "champion");
  assert.equal(channels.rows[0].validation_status, "passed");

  await db.exec(`
    update public.v20_market_context
    set regime = 'bear',
        regime_score = -35,
        global_context = '{"sp500":{"value":6100,"dataDate":"2026-07-16"}}',
        updated_at = clock_timestamp()
    where data_date = current_date - 5 and model_version = '20.1';

    update public.v20_model_signals
    set opportunity_score = 79,
        net_opportunity_score = 79,
        updated_at = updated_at + interval '2 seconds'
    where symbol = '1001' and model_key = 'short' and horizon_days = 2;
    insert into public.v20_model_dirty_queue (
      symbol, data_date, group_name, model_version, status,
      dirty_version, claimed_version, attempt_count, max_attempts
    ) values (
      '1001', current_date - 5, 'listed', '20.1', 'pending',
      2, null, 0, 5
    );
  `);
  const mutatedStateBeforeRevision = (
    await db.query("select public.twss_v20_read_publication_state() result")
  ).rows[0].result;
  assert.equal(mutatedStateBeforeRevision.marketContext.regime, "sideways",
    "mutable context changes must not rewrite the published run snapshot");
  const revisedMarketContext = (
    await db.query(`
      select pg_catalog.to_jsonb(c) market_context
      from public.v20_market_context c
      where c.data_date = current_date - 5 and c.model_version = '20.1'
    `)
  ).rows[0].market_context;
  const revisedDataCutoffAt = (
    await db.query(
      `select public.twss_v20_signal_data_cutoff(
        jsonb_build_object('dataDate', (current_date - 5)::text, 'modelVersion', '20.1')
      ) result`,
    )
  ).rows[0].result.dataCutoffAt;
  const revisedManifests = buildV20PublicationManifests({
    dataDate: dates.data_date,
    dataCutoffAt: revisedDataCutoffAt,
    sourceDates: { listed: dates.data_date, otc: dates.data_date, etf: dates.data_date, universe: dates.data_date },
    groupCounts: { listed: 5, otc: 0, etf: 0 },
    marketContext: revisedMarketContext,
  });
  const revisedRequest = {
    ...request,
    dataCutoffAt: revisedDataCutoffAt,
    codeHash: V20_MODEL_ARTIFACT_HASH,
    sourceHash: "c".repeat(64),
    ...revisedManifests,
    sourceManifest: { ...revisedManifests.sourceManifest, revision: 2 },
    marketContext: revisedMarketContext,
    marketRegime: "bear",
  };
  await assert.rejects(
    db.query(
      "select public.twss_v20_publish_recommendation_run($1::jsonb)",
      [JSON.stringify(revisedRequest)],
    ),
    /v20_dirty_queue_not_settled/,
  );
  await db.exec("delete from public.v20_model_dirty_queue");
  const revisedPublication = (
    await db.query(
      "select public.twss_v20_publish_recommendation_run($1::jsonb) result",
      [JSON.stringify(revisedRequest)],
    )
  ).rows[0].result;
  assert.equal(revisedPublication.revision, 2);
  assert.notEqual(revisedPublication.runId, publication.runId);
  const revisedState = (
    await db.query("select public.twss_v20_read_publication_state() result")
  ).rows[0].result;
  assert.equal(revisedState.marketContext.regime, "bear");
  assert.notDeepEqual(revisedState.marketContext, storedMarketContext);

  // A newer revision that was also available before entry supersedes every
  // item from the older same-day run. It must not double count stale ranks.
  await db.exec(`
    insert into public.v20_recommendation_runs (
      publication_key, data_date, data_cutoff_at, revision, status,
      model_version, feature_version, cost_model_version, calibration_version,
      code_hash, source_version, source_hash, source_manifest, model_manifest,
      market_context_snapshot, market_regime, expected_symbol_count,
      scored_symbol_count, signal_count, eligible_item_count,
      research_item_count, cycle_completeness, deadletter_count,
      terminal_errors, content_hash, published_by, published_at, created_at
    )
    select
      repeat('b', 64), data_date, data_cutoff_at, 3, status,
      model_version, feature_version, cost_model_version, calibration_version,
      code_hash, source_version, source_hash, source_manifest, model_manifest,
      market_context_snapshot, market_regime, expected_symbol_count,
      scored_symbol_count, signal_count, eligible_item_count,
      research_item_count, cycle_completeness, deadletter_count,
      terminal_errors, repeat('b', 64), published_by,
      pg_catalog.timezone('Asia/Taipei', (current_date - 4)::timestamp)
        - interval '30 minutes',
      created_at
    from public.v20_recommendation_runs
    where id = ${Number(publication.runId)};
  `);

  const supersededValidation = (
    await db.query(`
      select public.twss_v20_read_validation_summary(
        '{"modelKey":"short","horizonDays":2,"topN":100}'::jsonb
      ) result
    `)
  ).rows[0].result;
  assert.equal(supersededValidation.status, "insufficient_data");
  assert.equal(supersededValidation.sampleCount, 0,
    "an older run must be excluded when a later pre-entry revision exists");

  await assert.rejects(
    db.query(
      `update public.v20_publication_head
       set publication_key = $1
       where audience = 'public'`,
      [publication.publicationKey],
    ),
    /foreign key/i,
  );

  console.log("v20 immutable SQL runtime checks passed", {
    recommendationItems: counts.items,
    publicItems: counts.public_items,
    outcomeObservations: firstEvaluation.inserted,
  });
} finally {
  await db.close();
}

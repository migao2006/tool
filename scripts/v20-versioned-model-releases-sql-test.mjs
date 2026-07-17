import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { PGlite } from "@electric-sql/pglite";

const migrationUrl = new URL(
  "../supabase/migrations/20260716184500_allow_versioned_calibrated_model_releases.sql",
  import.meta.url,
);
const sql = await readFile(migrationUrl, "utf8");

assert.match(
  sql,
  /create unique index if not exists v20_model_releases_versioned_identity_uq[\s\S]+coalesce\(calibration_version, ''\)/i,
);
assert.match(sql, /v_artifact_hash !~ '\^\[0-9a-f\]\{64\}\$'/i);
assert.match(sql, /:calibration:[\s\S]+coalesce\(v_calibration_version, '<none>'\)/i);
assert.ok(
  (sql.match(/calibration_version is not distinct from v_calibration_version/gi) || []).length >= 3,
  "all release identity checks must use null-safe calibration equality",
);
assert.doesNotMatch(
  sql,
  /update\s+public\.v20_model_releases/i,
  "registration must never mutate an existing immutable release",
);
assert.doesNotMatch(
  sql,
  /pg_catalog\.(?:coalesce|nullif|greatest|least)\s*\(/i,
  "Postgres special forms must not be schema-qualified",
);

const db = new PGlite();
const artifactUpper = "A".repeat(64);
const artifactLower = artifactUpper.toLowerCase();

function releasePayload({
  calibrationVersion,
  validationStatus = "shadow",
  marker = "original",
  artifactHash = artifactUpper,
} = {}) {
  const payload = {
    modelKey: "short",
    modelVersion: "20.1",
    artifactHash,
    featureVersion: "features-20.1",
    costModelVersion: "taiwan-cost-2026.1",
    validationStatus,
    configuration: { marker },
    validationMetrics: { test: true },
    registeredBy: "pglite-versioned-release-test",
  };
  if (calibrationVersion !== undefined) payload.calibrationVersion = calibrationVersion;
  return payload;
}

async function register(payload) {
  const result = await db.query(
    "select public.twss_v20_register_model_release($1::jsonb) release_id",
    [JSON.stringify(payload)],
  );
  return Number(result.rows[0].release_id);
}

try {
  await db.exec(`
    create role anon;
    create role authenticated;
    create role service_role bypassrls;

    create table public.v20_model_releases (
      id bigint generated always as identity primary key,
      model_key text not null check (model_key in ('short', 'medium')),
      model_version text not null,
      artifact_hash text not null check (artifact_hash ~ '^[0-9A-Fa-f]{7,128}$'),
      feature_version text not null,
      cost_model_version text not null,
      calibration_version text,
      validation_status text not null default 'shadow'
        check (validation_status in ('shadow', 'passed', 'failed')),
      configuration jsonb not null default '{}'::jsonb,
      validation_metrics jsonb not null default '{}'::jsonb,
      registered_by text not null default 'service_role',
      registered_at timestamptz not null default clock_timestamp(),
      unique (model_key, model_version, artifact_hash)
    );

    create table public.v20_model_validation_events (
      id bigint generated always as identity primary key,
      release_id bigint not null references public.v20_model_releases(id),
      validation_status text not null,
      validation_metrics jsonb not null,
      window_start date,
      window_end date,
      notes text,
      recorded_by text not null,
      recorded_at timestamptz not null default clock_timestamp()
    );

    alter table public.v20_model_releases enable row level security;
    alter table public.v20_model_validation_events enable row level security;
    revoke all on table public.v20_model_releases, public.v20_model_validation_events
      from public, anon, authenticated, service_role;
    grant select on table public.v20_model_releases, public.v20_model_validation_events
      to service_role;
  `);

  await db.exec(sql);
  await db.exec(sql);

  const privileges = (
    await db.query(`
      select
        has_function_privilege(
          'anon', 'public.twss_v20_register_model_release(jsonb)', 'execute'
        ) anon_execute,
        has_function_privilege(
          'authenticated', 'public.twss_v20_register_model_release(jsonb)', 'execute'
        ) authenticated_execute,
        has_function_privilege(
          'service_role', 'public.twss_v20_register_model_release(jsonb)', 'execute'
        ) service_execute
    `)
  ).rows[0];
  assert.deepEqual(privileges, {
    anon_execute: false,
    authenticated_execute: false,
    service_execute: true,
  });

  const oldConstraintCount = Number((
    await db.query(`
      select pg_catalog.count(*) constraint_count
      from pg_catalog.pg_constraint c
      where c.conrelid = 'public.v20_model_releases'::regclass
        and c.contype = 'u'
        and pg_catalog.pg_get_constraintdef(c.oid)
          = 'UNIQUE (model_key, model_version, artifact_hash)'
    `)
  ).rows[0].constraint_count);
  assert.equal(oldConstraintCount, 0, "the legacy three-column unique constraint must be removed");

  const versionedIndex = (
    await db.query(`
      select indexdef
      from pg_catalog.pg_indexes
      where schemaname = 'public'
        and indexname = 'v20_model_releases_versioned_identity_uq'
    `)
  ).rows[0]?.indexdef;
  assert.match(versionedIndex || "", /unique index/i);
  assert.match(versionedIndex || "", /coalesce\(calibration_version, ''::text\)/i);

  await db.exec("set role anon");
  try {
    await assert.rejects(register(releasePayload()), /permission denied/i);
  } finally {
    await db.exec("reset role");
  }

  await db.exec("set role service_role");
  try {
    await assert.rejects(
      register(releasePayload({ artifactHash: "a".repeat(63) })),
      /v20_invalid_model_release/,
    );

    const baselineId = await register(releasePayload());
    const repeatedBaselineId = await register(releasePayload({
      calibrationVersion: "",
      validationStatus: "passed",
      marker: "must-not-overwrite",
      artifactHash: artifactLower,
    }));
    assert.equal(repeatedBaselineId, baselineId, "null calibration baseline must be idempotent");

    const calibrationAId = await register(releasePayload({
      calibrationVersion: "cal-A",
      validationStatus: "passed",
      marker: "cal-A-original",
      artifactHash: artifactLower,
    }));
    const repeatedCalibrationAId = await register(releasePayload({
      calibrationVersion: "cal-A",
      validationStatus: "failed",
      marker: "must-not-overwrite-cal-A",
    }));
    assert.equal(repeatedCalibrationAId, calibrationAId, "cal-A must be idempotent");

    const calibrationBId = await register(releasePayload({
      calibrationVersion: "cal-B",
      validationStatus: "passed",
      marker: "cal-B-original",
    }));
    const repeatedCalibrationBId = await register(releasePayload({
      calibrationVersion: "cal-B",
      marker: "must-not-overwrite-cal-B",
    }));
    assert.equal(repeatedCalibrationBId, calibrationBId, "cal-B must be idempotent");

    assert.equal(new Set([baselineId, calibrationAId, calibrationBId]).size, 3);

    const releases = (
      await db.query(`
        select
          id,
          artifact_hash,
          calibration_version,
          validation_status,
          configuration ->> 'marker' marker
        from public.v20_model_releases
        order by id
      `)
    ).rows;
    assert.deepEqual(
      releases.map((release) => ({
        id: Number(release.id),
        artifactHash: release.artifact_hash,
        calibrationVersion: release.calibration_version,
        validationStatus: release.validation_status,
        marker: release.marker,
      })),
      [
        {
          id: baselineId,
          artifactHash: artifactLower,
          calibrationVersion: null,
          validationStatus: "shadow",
          marker: "original",
        },
        {
          id: calibrationAId,
          artifactHash: artifactLower,
          calibrationVersion: "cal-A",
          validationStatus: "passed",
          marker: "cal-A-original",
        },
        {
          id: calibrationBId,
          artifactHash: artifactLower,
          calibrationVersion: "cal-B",
          validationStatus: "passed",
          marker: "cal-B-original",
        },
      ],
      "idempotent calls must not mutate prior release rows",
    );

    const eventCount = Number((
      await db.query("select pg_catalog.count(*) event_count from public.v20_model_validation_events")
    ).rows[0].event_count);
    assert.equal(eventCount, 3, "only new release identities create validation events");
  } finally {
    await db.exec("reset role");
  }

  console.log("v20 versioned calibrated model release SQL checks passed");
} finally {
  await db.close();
}

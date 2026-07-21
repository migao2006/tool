import { evaluateSnapshotFreshness } from "../freshness.ts";
import type {
  PredictionRunRow,
  TradingCalendarObservationRow,
} from "../types.ts";
import { assert, assertEquals } from "./assertions.ts";
import { snapshotRows } from "./fixtures.ts";

const DAY_MS = 86_400_000;

function dateRange(start: string, end: string): string[] {
  const values: string[] = [];
  for (
    let value = Date.parse(`${start}T00:00:00Z`);
    value <= Date.parse(`${end}T00:00:00Z`);
    value += DAY_MS
  ) values.push(new Date(value).toISOString().slice(0, 10));
  return values;
}

function calendar(
  start: string,
  end: string,
  closures: ReadonlySet<string> = new Set(),
): TradingCalendarObservationRow[] {
  return dateRange(start, end).map((tradingDate) => {
    const weekday = new Date(`${tradingDate}T00:00:00Z`).getUTCDay();
    const isTradingDay = weekday !== 0 && weekday !== 6 &&
      !closures.has(tradingDate);
    return {
      market: "TWSE",
      trading_date: tradingDate,
      is_trading_day: isTradingDay,
      decision_data_cutoff_at: isTradingDay ? `${tradingDate}T09:00:00Z` : null,
      calendar_verification_status: "VERIFIED",
      market_basis: "SOURCE_ASSERTED",
      available_at: `${tradingDate}T00:00:00Z`,
      usage_scope: "POINT_IN_TIME_CALENDAR",
      system_status: "PASS",
    };
  });
}

type PredictionRunOverrides = Partial<
  Pick<PredictionRunRow, "as_of_date" | "latest_available_at">
>;

function run(overrides: PredictionRunOverrides = {}): PredictionRunRow {
  return { ...snapshotRows().run, ...overrides };
}

Deno.test("verified long-weekend coverage keeps the last completed session fresh", () => {
  const observations = calendar(
    "2026-06-06",
    "2026-07-20",
    new Set(["2026-07-20"]),
  );
  const result = evaluateSnapshotFreshness(
    run({ as_of_date: "2026-07-17" }),
    observations,
    new Date("2026-07-21T02:00:00Z"),
  );

  assertEquals(result.stale, false);
  assertEquals(result.metadata.method, "TRADING_CALENDAR");
  assertEquals(result.metadata.expected_session_date, "2026-07-17");
  assertEquals(result.reasonCodes, []);
});

Deno.test("verified emergency closure does not create a phantom expected session", () => {
  const observations = calendar(
    "2026-06-07",
    "2026-07-21",
    new Set(["2026-07-21"]),
  );
  const result = evaluateSnapshotFreshness(
    run({ as_of_date: "2026-07-20" }),
    observations,
    new Date("2026-07-21T10:00:00Z"),
  );

  assertEquals(result.stale, false);
  assertEquals(result.metadata.expected_session_date, "2026-07-20");
});

Deno.test("configured publication readiness delays the current session", () => {
  const observations = calendar("2026-06-06", "2026-07-21");
  const result = evaluateSnapshotFreshness(
    run({ as_of_date: "2026-07-20" }),
    observations,
    new Date("2026-07-21T10:00:00Z"),
    { calendarReadyHourTaipei: 19 },
  );

  assertEquals(result.stale, false);
  assertEquals(result.metadata.expected_session_date, "2026-07-20");
  assertEquals(result.metadata.calendar_required_coverage_date, "2026-07-20");
});

Deno.test("a completed newer session marks an older snapshot stale", () => {
  const observations = calendar("2026-06-07", "2026-07-21");
  const result = evaluateSnapshotFreshness(
    run({ as_of_date: "2026-07-17" }),
    observations,
    new Date("2026-07-21T10:00:00Z"),
  );

  assertEquals(result.stale, true);
  assertEquals(result.metadata.expected_session_date, "2026-07-21");
  assert(result.reasonCodes.includes("STALE_PREDICTION_SNAPSHOT"));
});

Deno.test("a snapshot dated after the verified calendar fails closed", () => {
  const observations = calendar("2026-06-07", "2026-07-21");
  const result = evaluateSnapshotFreshness(
    run({ as_of_date: "2026-07-22" }),
    observations,
    new Date("2026-07-21T10:00:00Z"),
  );

  assertEquals(result.stale, true);
  assertEquals(result.metadata.expected_session_date, "2026-07-21");
  assert(
    result.reasonCodes.includes(
      "PREDICTION_SNAPSHOT_SESSION_AFTER_EXPECTED_CALENDAR",
    ),
  );
});

Deno.test("missing verified calendar coverage falls back to bounded wall clock", () => {
  const observations = calendar("2026-06-07", "2026-07-21");
  observations.splice(20, 1);
  const result = evaluateSnapshotFreshness(
    run({
      as_of_date: "2026-07-20",
      latest_available_at: "2026-07-21T08:00:00Z",
    }),
    observations,
    new Date("2026-07-21T10:00:00Z"),
  );

  assertEquals(result.stale, false);
  assertEquals(result.metadata.method, "WALL_CLOCK_FALLBACK");
  assert(
    result.reasonCodes.includes(
      "VERIFIED_TRADING_CALENDAR_COVERAGE_INCOMPLETE",
    ),
  );
  assert(
    result.reasonCodes.includes("PREDICTION_FRESHNESS_WALL_CLOCK_FALLBACK"),
  );
});

Deno.test("unavailable calendar and expired fallback both report stale", () => {
  const result = evaluateSnapshotFreshness(
    run({ latest_available_at: "2026-07-17T05:30:00Z" }),
    [],
    new Date("2026-07-21T10:00:00Z"),
    { fallbackStaleHours: 72 },
  );

  assertEquals(result.stale, true);
  assertEquals(result.metadata.calendar_status, "UNAVAILABLE");
  assert(result.reasonCodes.includes("VERIFIED_TRADING_CALENDAR_UNAVAILABLE"));
  assert(result.reasonCodes.includes("STALE_PREDICTION_SNAPSHOT"));
});

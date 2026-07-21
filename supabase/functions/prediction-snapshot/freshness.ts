import type {
  JsonRecord,
  PredictionRunRow,
  TradingCalendarObservationRow,
} from "./types.ts";

const TAIPEI_TIME_ZONE = "Asia/Taipei";
const DEFAULT_CALENDAR_READY_HOUR = 17;
const DEFAULT_CALENDAR_LOOKBACK_DAYS = 45;
const MILLISECONDS_PER_HOUR = 3_600_000;
const MILLISECONDS_PER_DAY = 86_400_000;

export interface FreshnessPolicy {
  fallbackStaleHours?: number;
  calendarReadyHourTaipei?: number;
  calendarLookbackDays?: number;
}

export interface FreshnessEvaluation {
  stale: boolean;
  reasonCodes: string[];
  metadata: JsonRecord;
}

interface TaipeiClock {
  date: string;
  hour: number;
}

function normalizedInteger(
  value: number | undefined,
  fallback: number,
  minimum: number,
  maximum: number,
): number {
  return Number.isInteger(value) && value !== undefined &&
      value >= minimum && value <= maximum
    ? value
    : fallback;
}

function taipeiClock(now: Date): TaipeiClock {
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone: TAIPEI_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    hourCycle: "h23",
  });
  const parts = Object.fromEntries(
    formatter.formatToParts(now).map((part) => [part.type, part.value]),
  );
  return {
    date: `${parts.year}-${parts.month}-${parts.day}`,
    hour: Number(parts.hour),
  };
}

function addUtcDays(isoDate: string, days: number): string {
  const timestamp = Date.parse(`${isoDate}T00:00:00Z`);
  return new Date(timestamp + days * MILLISECONDS_PER_DAY)
    .toISOString().slice(0, 10);
}

function compareIsoDates(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}

function requiredCoverageDate(now: Date, readyHourTaipei: number): string {
  const local = taipeiClock(now);
  return local.hour >= readyHourTaipei ? local.date : addUtcDays(local.date, -1);
}

function verifiedObservationMap(
  observations: TradingCalendarObservationRow[],
  now: Date,
): Map<string, TradingCalendarObservationRow> {
  const result = new Map<string, TradingCalendarObservationRow>();
  for (const row of observations) {
    const availableAt = Date.parse(row.available_at);
    if (
      row.calendar_verification_status !== "VERIFIED" ||
      row.market_basis !== "SOURCE_ASSERTED" ||
      row.usage_scope !== "POINT_IN_TIME_CALENDAR" ||
      row.system_status !== "PASS" ||
      !Number.isFinite(availableAt) ||
      availableAt > now.getTime()
    ) continue;
    result.set(row.trading_date, row);
  }
  return result;
}

function latestCompletedSession(
  observations: Iterable<TradingCalendarObservationRow>,
  now: Date,
  maximumTradingDate: string,
): TradingCalendarObservationRow | null {
  let latest: TradingCalendarObservationRow | null = null;
  for (const row of observations) {
    if (
      row.trading_date > maximumTradingDate ||
      !row.is_trading_day ||
      row.decision_data_cutoff_at === null
    ) continue;
    const cutoff = Date.parse(row.decision_data_cutoff_at);
    if (!Number.isFinite(cutoff) || cutoff > now.getTime()) continue;
    if (latest === null || row.trading_date > latest.trading_date) latest = row;
  }
  return latest;
}

function contiguousCoverage(
  observations: Map<string, TradingCalendarObservationRow>,
  endDate: string,
  lookbackDays: number,
): { complete: boolean; startDate: string; missingDate: string | null } {
  const startDate = addUtcDays(endDate, -(lookbackDays - 1));
  for (let offset = 0; offset < lookbackDays; offset += 1) {
    const date = addUtcDays(startDate, offset);
    if (!observations.has(date)) {
      return { complete: false, startDate, missingDate: date };
    }
  }
  return { complete: true, startDate, missingDate: null };
}

function wallClockFallback(
  run: PredictionRunRow,
  now: Date,
  fallbackStaleHours: number,
  calendarStatus: "UNAVAILABLE" | "INCOMPLETE",
  metadata: JsonRecord,
): FreshnessEvaluation {
  const latestAvailableAt = Date.parse(run.latest_available_at);
  const stale = !Number.isFinite(latestAvailableAt) ||
    now.getTime() - latestAvailableAt > fallbackStaleHours * MILLISECONDS_PER_HOUR;
  return {
    stale,
    reasonCodes: [
      "PREDICTION_FRESHNESS_WALL_CLOCK_FALLBACK",
      calendarStatus === "UNAVAILABLE"
        ? "VERIFIED_TRADING_CALENDAR_UNAVAILABLE"
        : "VERIFIED_TRADING_CALENDAR_COVERAGE_INCOMPLETE",
      ...(stale ? ["STALE_PREDICTION_SNAPSHOT"] : []),
    ],
    metadata: {
      method: "WALL_CLOCK_FALLBACK",
      calendar_status: calendarStatus,
      snapshot_session_date: run.as_of_date,
      expected_session_date: null,
      fallback_stale_after_hours: fallbackStaleHours,
      ...metadata,
    },
  };
}

export function evaluateSnapshotFreshness(
  run: PredictionRunRow,
  calendarObservations: TradingCalendarObservationRow[],
  now = new Date(),
  policy: FreshnessPolicy = {},
): FreshnessEvaluation {
  const fallbackStaleHours = normalizedInteger(
    policy.fallbackStaleHours,
    72,
    1,
    24 * 30,
  );
  const readyHour = normalizedInteger(
    policy.calendarReadyHourTaipei,
    DEFAULT_CALENDAR_READY_HOUR,
    0,
    23,
  );
  const lookbackDays = normalizedInteger(
    policy.calendarLookbackDays,
    DEFAULT_CALENDAR_LOOKBACK_DAYS,
    14,
    62,
  );
  const requiredDate = requiredCoverageDate(now, readyHour);
  const verified = verifiedObservationMap(calendarObservations, now);
  if (verified.size === 0) {
    return wallClockFallback(
      run,
      now,
      fallbackStaleHours,
      "UNAVAILABLE",
      {
        calendar_required_coverage_date: requiredDate,
        calendar_observation_count: 0,
      },
    );
  }

  const latestSession = latestCompletedSession(
    verified.values(),
    now,
    requiredDate,
  );
  if (latestSession === null) {
    return wallClockFallback(
      run,
      now,
      fallbackStaleHours,
      "INCOMPLETE",
      {
        calendar_required_coverage_date: requiredDate,
        calendar_observation_count: verified.size,
      },
    );
  }

  const coverageEnd = compareIsoDates(latestSession.trading_date, requiredDate) > 0
    ? latestSession.trading_date
    : requiredDate;
  const coverage = contiguousCoverage(verified, coverageEnd, lookbackDays);
  if (!coverage.complete) {
    return wallClockFallback(
      run,
      now,
      fallbackStaleHours,
      "INCOMPLETE",
      {
        calendar_required_coverage_date: requiredDate,
        calendar_coverage_start_date: coverage.startDate,
        calendar_coverage_end_date: coverageEnd,
        calendar_first_missing_date: coverage.missingDate,
        calendar_observation_count: verified.size,
      },
    );
  }

  const sessionComparison = compareIsoDates(
    run.as_of_date,
    latestSession.trading_date,
  );
  const stale = sessionComparison < 0;
  const sessionAfterCalendar = sessionComparison > 0;
  return {
    stale: stale || sessionAfterCalendar,
    reasonCodes: stale
      ? ["STALE_PREDICTION_SNAPSHOT"]
      : sessionAfterCalendar
      ? ["PREDICTION_SNAPSHOT_SESSION_AFTER_EXPECTED_CALENDAR"]
      : [],
    metadata: {
      method: "TRADING_CALENDAR",
      calendar_status: "VERIFIED",
      snapshot_session_date: run.as_of_date,
      expected_session_date: latestSession.trading_date,
      expected_session_cutoff_at: latestSession.decision_data_cutoff_at,
      calendar_required_coverage_date: requiredDate,
      calendar_coverage_start_date: coverage.startDate,
      calendar_coverage_end_date: coverageEnd,
      calendar_observation_count: verified.size,
      fallback_stale_after_hours: fallbackStaleHours,
    },
  };
}

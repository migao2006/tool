import type { JsonValue } from "./types.ts";

const REQUEST_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$/u;

export type LogFields = Readonly<Record<string, JsonValue>>;

export interface RequestLogger {
  info(fields: LogFields): void;
  error(fields: LogFields): void;
}

export const consoleRequestLogger: RequestLogger = Object.freeze({
  info(fields: LogFields) {
    console.info(JSON.stringify(fields));
  },
  error(fields: LogFields) {
    console.error(JSON.stringify(fields));
  },
});

export function requestId(request: Request): string {
  const supplied = request.headers.get("X-Request-Id")?.trim() ?? "";
  return REQUEST_ID_PATTERN.test(supplied) ? supplied : crypto.randomUUID();
}

export function elapsedMilliseconds(startedAt: number): number {
  return Math.max(0, Math.round((performance.now() - startedAt) * 100) / 100);
}

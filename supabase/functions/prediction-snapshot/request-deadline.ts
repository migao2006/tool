import { ApiError } from "./errors.ts";

const MAX_TIMEOUT_MS = 30_000;

export function normalizeTimeoutMs(
  value: number,
  fallback: number,
): number {
  return Number.isFinite(value) && value > 0
    ? Math.min(Math.trunc(value), MAX_TIMEOUT_MS)
    : fallback;
}

export async function runWithRequestDeadline<T>(
  timeoutMs: number,
  operation: (signal: AbortSignal) => Promise<T>,
): Promise<T> {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      const error = new ApiError(
        504,
        "PREDICTION_REQUEST_TIMEOUT",
        "Prediction snapshot request exceeded its deadline",
      );
      controller.abort(error);
      reject(error);
    }, timeoutMs);
  });

  try {
    return await Promise.race([operation(controller.signal), timeout]);
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
}

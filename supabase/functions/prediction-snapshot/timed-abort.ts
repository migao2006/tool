export interface TimedAbortSignal {
  signal: AbortSignal;
  cleanup(): void;
  timedOut(): boolean;
}

export function createTimedAbortSignal(
  parentSignal: AbortSignal | undefined,
  timeoutMs: number,
): TimedAbortSignal {
  const controller = new AbortController();
  let queryTimedOut = false;
  const abortFromParent = () => controller.abort(parentSignal?.reason);
  if (parentSignal?.aborted) abortFromParent();
  else parentSignal?.addEventListener("abort", abortFromParent, { once: true });
  const timer = setTimeout(() => {
    queryTimedOut = true;
    controller.abort();
  }, timeoutMs);
  return {
    signal: controller.signal,
    timedOut: () => queryTimedOut,
    cleanup: () => {
      clearTimeout(timer);
      parentSignal?.removeEventListener("abort", abortFromParent);
    },
  };
}

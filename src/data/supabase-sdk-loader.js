const SDK_URL = new URL("../vendor/supabase-2.110.7.min.js", import.meta.url);
const SCRIPT_ID = "alpha-lens-supabase-sdk";
const MAX_ATTEMPTS = 2;
const LOAD_TIMEOUT_MS = 8_000;

let sdkPromise;

function readCreateClient() {
  const createClient = globalThis.supabase?.createClient;
  return typeof createClient === "function" ? createClient : null;
}

function createLoadError(message, attempt) {
  const error = new Error(message);
  error.name = "SupabaseSdkLoadError";
  error.code = "SUPABASE_SDK_LOAD_FAILED";
  error.attempt = attempt;
  return error;
}

function attemptUrl(attempt) {
  const url = new URL(SDK_URL);
  if (attempt > 1) url.searchParams.set("retry", String(attempt));
  return url.toString();
}

function loadAttempt(attempt) {
  const available = readCreateClient();
  if (available) return Promise.resolve(available);

  return new Promise((resolve, reject) => {
    const documentRef = globalThis.document;
    if (!documentRef?.head) {
      reject(createLoadError("Supabase SDK 無法在目前環境載入。", attempt));
      return;
    }

    documentRef.getElementById(SCRIPT_ID)?.remove();
    const script = documentRef.createElement("script");
    script.id = SCRIPT_ID;
    script.async = true;
    script.dataset.supabaseSdk = "true";
    script.src = attemptUrl(attempt);

    let settled = false;
    const finish = (callback, value) => {
      if (settled) return;
      settled = true;
      globalThis.clearTimeout(timeoutId);
      script.removeEventListener("load", onLoad);
      script.removeEventListener("error", onError);
      callback(value);
    };
    const onLoad = () => {
      const createClient = readCreateClient();
      if (createClient) {
        finish(resolve, createClient);
      } else {
        finish(
          reject,
          createLoadError("Supabase SDK 已下載但未完成初始化。", attempt),
        );
      }
    };
    const onError = () => {
      script.remove();
      finish(reject, createLoadError("Supabase SDK 載入失敗。", attempt));
    };
    const timeoutId = globalThis.setTimeout(() => {
      script.remove();
      finish(reject, createLoadError("Supabase SDK 載入逾時。", attempt));
    }, LOAD_TIMEOUT_MS);

    script.addEventListener("load", onLoad, { once: true });
    script.addEventListener("error", onError, { once: true });
    documentRef.head.append(script);
  });
}

async function loadWithRetry() {
  let lastError;
  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt += 1) {
    try {
      return await loadAttempt(attempt);
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError;
}

export function loadSupabaseCreateClient() {
  const available = readCreateClient();
  if (available) return Promise.resolve(available);
  sdkPromise ??= loadWithRetry();
  return sdkPromise;
}

export function isSupabaseSdkLoadError(error) {
  return error?.code === "SUPABASE_SDK_LOAD_FAILED";
}

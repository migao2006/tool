const AUTH_QUERY_KEYS = Object.freeze([
  "auth_action",
  "code",
  "error",
  "error_code",
  "error_description",
  "state",
]);

const AUTH_QUERY_TRIGGER_KEYS = Object.freeze(
  AUTH_QUERY_KEYS.filter((key) => key !== "state"),
);

const AUTH_FRAGMENT_KEYS = Object.freeze([
  "access_token",
  "expires_at",
  "expires_in",
  "provider_refresh_token",
  "provider_token",
  "refresh_token",
  "token_type",
  "type",
  "error",
  "error_code",
  "error_description",
]);

function currentUrl(locationLike = globalThis.location) {
  return locationLike?.href ? new URL(locationLike.href) : null;
}

function fragmentParameters(url) {
  const fragment = url.hash.startsWith("#") ? url.hash.slice(1) : url.hash;
  return new URLSearchParams(fragment);
}

export function hasImplicitAuthCallback(locationLike = globalThis.location) {
  const url = currentUrl(locationLike);
  if (!url?.hash) return false;
  const parameters = fragmentParameters(url);
  return AUTH_FRAGMENT_KEYS.some((key) => parameters.has(key));
}

export function hasAuthCallback(locationLike = globalThis.location) {
  const url = currentUrl(locationLike);
  if (!url) return false;
  return hasImplicitAuthCallback(locationLike) ||
    AUTH_QUERY_TRIGGER_KEYS.some((key) => url.searchParams.has(key));
}

export function hasPasswordRecoveryIntent(locationLike = globalThis.location) {
  const url = currentUrl(locationLike);
  if (!url) return false;
  const fragment = fragmentParameters(url);
  return url.searchParams.get("auth_action") === "password-recovery" ||
    fragment.get("type") === "recovery";
}

export function readAuthCallbackError(locationLike = globalThis.location) {
  const url = currentUrl(locationLike);
  if (!url) return null;
  const fragment = fragmentParameters(url);
  const code = url.searchParams.get("error_code") ??
    fragment.get("error_code") ??
    url.searchParams.get("error") ??
    fragment.get("error");
  const message = url.searchParams.get("error_description") ??
    fragment.get("error_description");
  if (!code && !message) return null;
  const error = new Error(message || "Auth callback failed");
  error.code = code || "auth_callback_failed";
  return error;
}

export function sanitizeAuthCallbackUrl({
  locationLike = globalThis.location,
  historyLike = globalThis.history,
  fallbackHash = "#home",
} = {}) {
  const url = currentUrl(locationLike);
  if (!url || !historyLike?.replaceState || !hasAuthCallback(locationLike)) return;
  AUTH_QUERY_KEYS.forEach((key) => url.searchParams.delete(key));
  if (hasImplicitAuthCallback(locationLike)) url.hash = fallbackHash;
  historyLike.replaceState(
    historyLike.state,
    "",
    `${url.pathname}${url.search}${url.hash}`,
  );
}

const runtimeBaseUrl = globalThis.location
  ? new URL("./", globalThis.location.href).toString()
  : "";

function authRedirectUrl(action) {
  if (!runtimeBaseUrl) return "";
  const redirect = new URL(runtimeBaseUrl);
  redirect.searchParams.set("auth_action", action);
  return redirect.toString();
}

export const publicConfig = Object.freeze({
  supabaseUrl: "https://zuhwkxlmnvwiktcmijup.supabase.co",
  supabasePublishableKey: "sb_publishable_4T3QrbPrb0ZNzXceEYUqig_oWUpaoHd",
  authConfirmationRedirectUrl: authRedirectUrl("email-confirmation"),
  authPasswordRecoveryRedirectUrl: authRedirectUrl("password-recovery"),
  predictionApiBaseUrl: "https://zuhwkxlmnvwiktcmijup.supabase.co/functions/v1/",
  predictionApiTimeoutMs: 12_000,
  homeDataStatusTimeoutMs: 12_000,
  predictionApiContractVersion: "prediction-snapshot.v1",
  watchlistPersistenceEnabled: false,
});

export function hasSupabaseConfig(config = publicConfig) {
  return (
    /^https:\/\/[a-z0-9]+\.supabase\.co$/u.test(config.supabaseUrl) &&
    config.supabasePublishableKey.startsWith("sb_publishable_")
  );
}

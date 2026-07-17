const runtimeBaseUrl = globalThis.location
  ? new URL("./", globalThis.location.href).toString()
  : "";

export const publicConfig = Object.freeze({
  supabaseUrl: "https://zuhwkxlmnvwiktcmijup.supabase.co",
  supabasePublishableKey: "sb_publishable_4T3QrbPrb0ZNzXceEYUqig_oWUpaoHd",
  authConfirmationRedirectUrl: runtimeBaseUrl,
  predictionApiBaseUrl: "",
  predictionApiTimeoutMs: 12_000,
  predictionApiContractVersion: "prediction-snapshot.v1",
});

export function hasSupabaseConfig(config = publicConfig) {
  return (
    /^https:\/\/[a-z0-9]+\.supabase\.co$/u.test(config.supabaseUrl) &&
    config.supabasePublishableKey.startsWith("sb_publishable_")
  );
}

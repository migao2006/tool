const productionOrigin = "https://tool-dun-psi.vercel.app";
const runtimeOrigin = globalThis.location?.origin ?? productionOrigin;

export const publicConfig = Object.freeze({
  supabaseUrl: "https://zuhwkxlmnvwiktcmijup.supabase.co",
  supabasePublishableKey: "sb_publishable_4T3QrbPrb0ZNzXceEYUqig_oWUpaoHd",
  authRedirectUrl: `${runtimeOrigin}/?auth=recovery`,
});

export function hasSupabaseConfig(config = publicConfig) {
  return (
    /^https:\/\/[a-z0-9]+\.supabase\.co$/u.test(config.supabaseUrl) &&
    config.supabasePublishableKey.startsWith("sb_publishable_")
  );
}

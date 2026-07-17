import {
  hasSupabaseConfig,
  publicConfig,
} from "../core/public-config.js?v=auth-5";

let client;

export function createSupabaseClient(config = publicConfig) {
  if (!hasSupabaseConfig(config)) return null;

  const createClient = globalThis.supabase?.createClient;
  if (typeof createClient !== "function") {
    throw new Error("Supabase SDK 尚未載入。");
  }

  client ??= createClient(config.supabaseUrl, config.supabasePublishableKey, {
    auth: {
      autoRefreshToken: true,
      detectSessionInUrl: true,
      persistSession: true,
    },
  });

  return client;
}

import {
  hasSupabaseConfig,
  publicConfig,
} from "../core/public-config.js?v=auth-7";
import { loadSupabaseCreateClient } from "./supabase-sdk-loader.js?v=auth-1";

let client;

export async function createSupabaseClient(config = publicConfig) {
  if (!hasSupabaseConfig(config)) return null;

  const createClient = await loadSupabaseCreateClient();

  client ??= createClient(config.supabaseUrl, config.supabasePublishableKey, {
    auth: {
      autoRefreshToken: true,
      detectSessionInUrl: true,
      flowType: "pkce",
      persistSession: true,
    },
  });

  return client;
}

import { publicConfig } from "../core/public-config.js?v=api-3";
import { createSupabaseClient } from "./supabase-client.js?v=auth-5";

export async function readSupabaseAccessToken(config = publicConfig) {
  const client = createSupabaseClient(config);
  if (!client) return null;
  const { data, error } = await client.auth.getSession();
  if (error) throw error;
  return data.session?.access_token ?? null;
}

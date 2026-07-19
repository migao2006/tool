import { parseAllowedOrigins } from "./cors.ts";
import { createHandler } from "./handler.ts";
import { SnapshotRepository } from "./repository.ts";

const repository = new SnapshotRepository({
  supabaseUrl: Deno.env.get("SUPABASE_URL") ?? "",
  serviceRoleKey: Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "",
});

const staleHoursValue = Number(
  Deno.env.get("PREDICTION_STALE_AFTER_HOURS") ?? "72",
);
const staleHours = Number.isFinite(staleHoursValue) && staleHoursValue > 0
  ? staleHoursValue
  : 72;

Deno.serve(createHandler({
  repository,
  corsPolicy: parseAllowedOrigins(Deno.env.get("PREDICTION_ALLOWED_ORIGINS")),
  staleHours,
}));

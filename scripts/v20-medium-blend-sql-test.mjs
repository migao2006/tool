import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const migration = await readFile(new URL(
  "../supabase/migrations/20260717083846_add_v20_medium_blend_rankings.sql",
  import.meta.url,
), "utf8");

assert.match(migration, /create or replace function public\.twss_v20_read_medium_blend\(p_query jsonb default '\{\}'::jsonb\)/i);
assert.match(migration, /security definer[\s\S]*set search_path = ''/i);
assert.match(migration, /i\.model_key = 'medium'[\s\S]*i\.horizon_days in \(10, 20, 40\)/i);
assert.match(migration, /i\.public_visible[\s\S]*not i\.research_only[\s\S]*i\.is_eligible/i);
assert.match(migration, /having pg_catalog\.count\(\*\) = 3[\s\S]*count\(distinct c\.horizon_days\) = 3/i);
assert.match(migration, /when 10 then 0\.25 when 20 then 0\.50 when 40 then 0\.25/i);
assert.match(migration, /pg_catalog\.max\(c\.risk_score\) risk_score/i);
assert.match(migration, /pg_catalog\.min\(c\.confidence\) confidence/i);
assert.match(migration, /pg_catalog\.min\(c\.completeness\) completeness/i);
assert.match(migration, /order by b\.net_opportunity_score desc, b\.risk_score asc, b\.symbol asc/i);
assert.match(migration, /where blend_rank > v_after_rank/i);
assert.match(migration, /'componentHorizons', p\.component_horizons/i);
assert.match(migration, /'blendWeights', '\{"10":0\.25,"20":0\.50,"40":0\.25\}'::jsonb/i);
assert.match(migration, /revoke all on function public\.twss_v20_read_medium_blend\(jsonb\)[\s\S]*from public, anon, authenticated, service_role/i);
assert.match(migration, /grant execute on function public\.twss_v20_read_medium_blend\(jsonb\)[\s\S]*to anon, authenticated, service_role/i);

console.log("v20 medium blend SQL contract checks passed");

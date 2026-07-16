import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const migrationUrl = new URL(
  "../supabase/migrations/20260716024526_add_v20_signal_outcomes_calibration.sql",
  import.meta.url,
);
const sql = await readFile(migrationUrl, "utf8");
const normalized = sql.replace(/\s+/g, " ").toLowerCase();

const required = [
  "create table if not exists public.v20_signal_outcomes",
  "primary key (symbol, signal_date, model_key, horizon_days, model_version)",
  "references public.v20_model_signals(symbol, signal_date, model_key, horizon_days, model_version)",
  "alter table public.v20_signal_outcomes enable row level security",
  "revoke all on table public.v20_signal_outcomes from public, anon, authenticated, service_role",
  "grant select, insert, update on table public.v20_signal_outcomes to service_role",
  "security invoker",
  "s.official",
  "s.gate_passed",
  "ss.trade_date > s.signal_date",
  "ss.trade_date <= p_as_of_date",
  "limit p_limit",
  "p_limit > 500",
  "stop_first_same_bar",
  "p_buy_commission_rate",
  "p_sell_commission_rate",
  "p_stock_sell_tax_rate",
  "p_etf_sell_tax_rate",
  "p_slippage_rate_per_side",
  "p_spread_rate_per_side",
  "'all'::text as bucket_strategy_key",
  "(-1)::smallint as bucket_score_decile",
  "on conflict (model_key, model_version, strategy_key, horizon_days, market_regime, score_decile)",
  "training_start",
  "training_end",
  "calibration_date",
];

for (const fragment of required) {
  assert.ok(normalized.includes(fragment), `missing SQL invariant: ${fragment}`);
}

assert.equal(
  (normalized.match(/security invoker/g) || []).length >= 2,
  true,
  "both service RPCs must be SECURITY INVOKER",
);
assert.equal(
  normalized.includes("security definer"),
  false,
  "the additive outcome migration must not create SECURITY DEFINER code",
);
assert.equal(
  /grant\s+execute[\s\S]*?to\s+(?:anon|authenticated)/i.test(sql),
  false,
  "outcome/calibration RPCs must not be executable by public API roles",
);
assert.ok(
  /horizon_exit_date\s*<=\s*p_as_of_date/i.test(sql),
  "calibration/evaluation must exclude horizons after the as-of date",
);

console.log("v20 signal outcome SQL static checks passed");

-- Taiwan Stock Smart v16.2: persistent, incrementally refreshed market data.
-- Existing user/auth/journal tables are intentionally untouched.

create extension if not exists pg_net with schema extensions;
create extension if not exists pg_cron with schema pg_catalog;

alter table public.stock_master
  add column if not exists active boolean not null default true,
  add column if not exists last_trade_date date,
  add column if not exists metadata jsonb not null default '{}'::jsonb;

alter table public.stock_snapshots
  add column if not exists market text,
  add column if not exists industry text,
  add column if not exists instrument_type text not null default '股票',
  add column if not exists open numeric,
  add column if not exists high numeric,
  add column if not exists low numeric,
  add column if not exists trade_value numeric,
  add column if not exists transactions bigint,
  add column if not exists trust_buy bigint,
  add column if not exists dealer_buy bigint,
  add column if not exists margin_balance bigint,
  add column if not exists short_balance bigint,
  add column if not exists preliminary_score numeric,
  add column if not exists peer_context jsonb not null default '{}'::jsonb,
  add column if not exists source_dates jsonb not null default '{}'::jsonb;

create index if not exists stock_snapshots_market_score_idx
  on public.stock_snapshots (trade_date desc, market, preliminary_score desc);
create index if not exists stock_snapshots_type_score_idx
  on public.stock_snapshots (trade_date desc, instrument_type, preliminary_score desc);

create table if not exists public.stock_price_history (
  symbol text not null references public.stock_master(symbol) on delete cascade,
  trade_date date not null,
  open numeric,
  high numeric,
  low numeric,
  close numeric not null,
  volume numeric,
  trade_value numeric,
  transactions bigint,
  source text not null default 'FinMind TaiwanStockPrice',
  updated_at timestamptz not null default now(),
  primary key (symbol, trade_date)
);
create index if not exists stock_price_history_date_idx
  on public.stock_price_history (trade_date desc);

create table if not exists public.stock_monthly_revenues (
  symbol text not null references public.stock_master(symbol) on delete cascade,
  revenue_period text not null check (revenue_period ~ '^\d{4}-\d{2}$'),
  revenue_year integer not null,
  revenue_month integer not null check (revenue_month between 1 and 12),
  revenue numeric not null,
  mom numeric,
  yoy numeric,
  available_at date,
  source text not null default 'FinMind TaiwanStockMonthRevenue',
  updated_at timestamptz not null default now(),
  primary key (symbol, revenue_period)
);
create index if not exists stock_monthly_revenues_period_idx
  on public.stock_monthly_revenues (revenue_period desc);

create table if not exists public.stock_quarterly_financials (
  symbol text not null references public.stock_master(symbol) on delete cascade,
  report_period text not null,
  report_date date not null,
  available_at date,
  revenue numeric,
  net_income numeric,
  eps numeric,
  gross_margin numeric,
  operating_margin numeric,
  net_margin numeric,
  roe numeric,
  operating_cash_flow numeric,
  free_cash_flow numeric,
  cash_conversion numeric,
  inventory numeric,
  receivables numeric,
  debt_ratio numeric,
  current_ratio numeric,
  interest_coverage numeric,
  non_operating_ratio numeric,
  source text not null default 'FinMind financial statements',
  updated_at timestamptz not null default now(),
  primary key (symbol, report_period)
);
create index if not exists stock_quarterly_financials_date_idx
  on public.stock_quarterly_financials (report_date desc);

create table if not exists public.stock_institutional_flows (
  symbol text not null references public.stock_master(symbol) on delete cascade,
  trade_date date not null,
  foreign_net numeric,
  trust_net numeric,
  dealer_net numeric,
  institutional_net numeric,
  volume_intensity numeric,
  source text not null default 'FinMind institutional investors',
  updated_at timestamptz not null default now(),
  primary key (symbol, trade_date)
);
create index if not exists stock_institutional_flows_date_idx
  on public.stock_institutional_flows (trade_date desc);

create table if not exists public.stock_margin_history (
  symbol text not null references public.stock_master(symbol) on delete cascade,
  trade_date date not null,
  margin_balance numeric,
  margin_limit numeric,
  short_balance numeric,
  source text not null default 'FinMind margin and short sale',
  updated_at timestamptz not null default now(),
  primary key (symbol, trade_date)
);
create index if not exists stock_margin_history_date_idx
  on public.stock_margin_history (trade_date desc);

create table if not exists public.stock_analysis_cache (
  symbol text primary key references public.stock_master(symbol) on delete cascade,
  group_name text not null check (group_name in ('listed', 'otc', 'etf')),
  data_date date,
  analysis_version text not null,
  score numeric,
  confidence numeric not null default 0 check (confidence between 0 and 100),
  official boolean not null default false,
  tier text,
  stock jsonb not null default '{}'::jsonb,
  analysis jsonb,
  result jsonb,
  status text not null default 'pending' check (status in ('pending', 'ready', 'error')),
  last_error text,
  fetched_at timestamptz,
  updated_at timestamptz not null default now()
);
create index if not exists stock_analysis_cache_rank_idx
  on public.stock_analysis_cache (group_name, score desc, confidence desc)
  where status = 'ready';
create index if not exists stock_analysis_cache_date_idx
  on public.stock_analysis_cache (data_date desc);

create table if not exists public.opportunity_score_history (
  symbol text not null references public.stock_master(symbol) on delete cascade,
  score_date date not null,
  model_version text not null,
  group_name text not null check (group_name in ('listed', 'otc', 'etf')),
  score numeric,
  confidence numeric not null default 0 check (confidence between 0 and 100),
  official boolean not null default false,
  tier text,
  categories jsonb not null default '[]'::jsonb,
  risk jsonb not null default '{}'::jsonb,
  result jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  primary key (symbol, score_date, model_version)
);
create index if not exists opportunity_score_history_rank_idx
  on public.opportunity_score_history (score_date desc, group_name, score desc);

create table if not exists public.stock_sync_state (
  job_key text primary key,
  group_name text,
  cycle_date date,
  cursor_offset integer not null default 0 check (cursor_offset >= 0),
  total_items integer not null default 0 check (total_items >= 0),
  processed_count integer not null default 0 check (processed_count >= 0),
  cycle_number integer not null default 0 check (cycle_number >= 0),
  status text not null default 'pending' check (status in ('pending', 'running', 'success', 'partial', 'error')),
  last_symbol text,
  last_error text,
  started_at timestamptz,
  last_success_at timestamptz,
  next_run_at timestamptz,
  details jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

insert into public.stock_sync_state (job_key, group_name)
values
  ('universe', null),
  ('deep_listed', 'listed'),
  ('deep_otc', 'otc'),
  ('deep_etf', 'etf')
on conflict (job_key) do nothing;

-- Public clients can read official market data but cannot mutate it.
alter table public.stock_price_history enable row level security;
alter table public.stock_monthly_revenues enable row level security;
alter table public.stock_quarterly_financials enable row level security;
alter table public.stock_institutional_flows enable row level security;
alter table public.stock_margin_history enable row level security;
alter table public.stock_analysis_cache enable row level security;
alter table public.opportunity_score_history enable row level security;
alter table public.stock_sync_state enable row level security;

create policy stock_price_history_public_read on public.stock_price_history
  for select to anon, authenticated using (true);
create policy stock_monthly_revenues_public_read on public.stock_monthly_revenues
  for select to anon, authenticated using (true);
create policy stock_quarterly_financials_public_read on public.stock_quarterly_financials
  for select to anon, authenticated using (true);
create policy stock_institutional_flows_public_read on public.stock_institutional_flows
  for select to anon, authenticated using (true);
create policy stock_margin_history_public_read on public.stock_margin_history
  for select to anon, authenticated using (true);
create policy stock_analysis_cache_public_read on public.stock_analysis_cache
  for select to anon, authenticated using (true);
create policy opportunity_score_history_public_read on public.opportunity_score_history
  for select to anon, authenticated using (true);
create policy stock_sync_state_public_read on public.stock_sync_state
  for select to anon, authenticated using (true);

revoke all on
  public.stock_price_history,
  public.stock_monthly_revenues,
  public.stock_quarterly_financials,
  public.stock_institutional_flows,
  public.stock_margin_history,
  public.stock_analysis_cache,
  public.opportunity_score_history,
  public.stock_sync_state
from anon, authenticated;

grant select on
  public.stock_price_history,
  public.stock_monthly_revenues,
  public.stock_quarterly_financials,
  public.stock_institutional_flows,
  public.stock_margin_history,
  public.stock_analysis_cache,
  public.opportunity_score_history,
  public.stock_sync_state
to anon, authenticated;

grant all on
  public.stock_price_history,
  public.stock_monthly_revenues,
  public.stock_quarterly_financials,
  public.stock_institutional_flows,
  public.stock_margin_history,
  public.stock_analysis_cache,
  public.opportunity_score_history,
  public.stock_sync_state
to service_role;

-- Create an internal token without placing its plaintext in source control.
do $$
begin
  if not exists (select 1 from vault.secrets where name = 'twss_sync_token') then
    perform vault.create_secret(
      encode(extensions.gen_random_bytes(32), 'hex'),
      'twss_sync_token',
      'Internal token for the Taiwan Stock Smart batch scheduler'
    );
  end if;
end
$$;

create or replace function public.twss_verify_sync_token(p_token text)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from vault.decrypted_secrets
    where name = 'twss_sync_token'
      and decrypted_secret = p_token
  );
$$;

revoke all on function public.twss_verify_sync_token(text) from public, anon, authenticated;
grant execute on function public.twss_verify_sync_token(text) to service_role;

-- Fix the pre-existing trigger helper warning without changing its behavior.
alter function public.set_updated_at() set search_path = '';

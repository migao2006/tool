create schema if not exists market_data;

create table if not exists market_data.data_sources (
  source_id bigint generated always as identity primary key,
  source_code text not null unique,
  display_name text not null,
  source_timezone text not null,
  revision_policy text not null,
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists market_data.trading_calendar (
  market text not null check (market in ('TWSE', 'TPEX', 'US')),
  trading_date date not null,
  is_trading_day boolean not null,
  opens_at timestamptz,
  closes_at timestamptz,
  decision_data_cutoff_at timestamptz,
  source_id bigint not null references market_data.data_sources(source_id),
  available_at timestamptz not null,
  ingested_at timestamptz not null default now(),
  primary key (market, trading_date)
);

create table if not exists market_data.securities (
  security_id bigint generated always as identity primary key,
  symbol text not null,
  display_name text not null,
  market text not null check (market in ('TWSE', 'TPEX', 'ETF')),
  asset_type text not null check (asset_type in ('COMMON_STOCK', 'ETF')),
  currency text not null default 'TWD',
  listing_date date,
  delisting_date date,
  isin text,
  source_id bigint not null references market_data.data_sources(source_id),
  created_at timestamptz not null default now(),
  unique (market, symbol),
  check (delisting_date is null or listing_date is null or delisting_date >= listing_date)
);

create table if not exists market_data.security_history (
  security_history_id bigint generated always as identity primary key,
  security_id bigint not null references market_data.securities(security_id),
  effective_from date not null,
  effective_to date,
  industry_code text,
  industry_name text,
  trading_status text not null,
  attention_flag boolean not null default false,
  disposal_flag boolean not null default false,
  altered_trading_method_flag boolean not null default false,
  full_cash_delivery_flag boolean not null default false,
  periodic_auction_flag boolean not null default false,
  suspended_flag boolean not null default false,
  source_id bigint not null references market_data.data_sources(source_id),
  source_version text not null,
  available_at timestamptz not null,
  ingested_at timestamptz not null default now(),
  unique (security_id, effective_from, source_id, source_version),
  check (effective_to is null or effective_to >= effective_from)
);

create table if not exists market_data.benchmark_definitions (
  benchmark_id bigint generated always as identity primary key,
  benchmark_code text not null,
  benchmark_version text not null,
  market text not null check (market in ('TWSE', 'TPEX', 'ETF')),
  index_symbol text not null,
  effective_from date not null,
  effective_to date,
  available_at timestamptz not null,
  metadata jsonb not null default '{}'::jsonb,
  unique (benchmark_code, benchmark_version),
  check (effective_to is null or effective_to >= effective_from)
);

create table if not exists market_data.daily_bars (
  daily_bar_id bigint generated always as identity primary key,
  security_id bigint not null references market_data.securities(security_id),
  trade_date date not null,
  raw_open numeric(20,6),
  raw_high numeric(20,6),
  raw_low numeric(20,6),
  raw_close numeric(20,6),
  volume_shares numeric(24,4),
  turnover_ntd numeric(24,4),
  trade_count bigint,
  adjustment_factor numeric(24,12),
  cash_dividend_per_share numeric(20,8) not null default 0,
  company_action_complete boolean not null default false,
  opening_trade_available boolean not null default false,
  closing_trade_available boolean not null default false,
  limit_up_price numeric(20,6),
  limit_down_price numeric(20,6),
  best_bid numeric(20,6),
  best_ask numeric(20,6),
  source_id bigint not null references market_data.data_sources(source_id),
  source_version text not null,
  available_at timestamptz not null,
  ingested_at timestamptz not null default now(),
  unique (security_id, trade_date, source_id, source_version),
  check (raw_high is null or raw_low is null or raw_high >= raw_low),
  check (volume_shares is null or volume_shares >= 0),
  check (turnover_ntd is null or turnover_ntd >= 0)
);

create table if not exists market_data.corporate_actions (
  corporate_action_id bigint generated always as identity primary key,
  security_id bigint not null references market_data.securities(security_id),
  action_type text not null check (
    action_type in ('CASH_DIVIDEND', 'STOCK_DIVIDEND', 'SPLIT', 'CAPITAL_REDUCTION', 'RIGHTS', 'OTHER')
  ),
  ex_date date not null,
  payable_date date,
  cash_amount_per_share numeric(20,8),
  share_ratio numeric(20,10),
  reference_price_adjustment numeric(20,8),
  announced_at timestamptz not null,
  available_at timestamptz not null,
  source_id bigint not null references market_data.data_sources(source_id),
  source_version text not null,
  ingested_at timestamptz not null default now(),
  unique (security_id, action_type, ex_date, source_id, source_version),
  check (available_at >= announced_at)
);

create table if not exists market_data.institutional_flows (
  institutional_flow_id bigint generated always as identity primary key,
  security_id bigint not null references market_data.securities(security_id),
  trade_date date not null,
  foreign_net_shares numeric(24,4),
  investment_trust_net_shares numeric(24,4),
  dealer_net_shares numeric(24,4),
  foreign_holding_ratio numeric(12,8),
  source_id bigint not null references market_data.data_sources(source_id),
  source_version text not null,
  available_at timestamptz not null,
  ingested_at timestamptz not null default now(),
  unique (security_id, trade_date, source_id, source_version)
);

create table if not exists market_data.financing_short_facts (
  financing_short_id bigint generated always as identity primary key,
  security_id bigint not null references market_data.securities(security_id),
  trade_date date not null,
  margin_balance_shares numeric(24,4),
  margin_change_shares numeric(24,4),
  short_balance_shares numeric(24,4),
  short_change_shares numeric(24,4),
  borrowed_sell_shares numeric(24,4),
  source_id bigint not null references market_data.data_sources(source_id),
  source_version text not null,
  available_at timestamptz not null,
  ingested_at timestamptz not null default now(),
  unique (security_id, trade_date, source_id, source_version)
);

create table if not exists market_data.market_observations (
  market_observation_id bigint generated always as identity primary key,
  series_code text not null,
  observation_at timestamptz not null,
  numeric_value numeric(24,10),
  text_value text,
  source_id bigint not null references market_data.data_sources(source_id),
  source_version text not null,
  available_at timestamptz not null,
  ingested_at timestamptz not null default now(),
  unique (series_code, observation_at, source_id, source_version),
  check (numeric_value is not null or text_value is not null)
);


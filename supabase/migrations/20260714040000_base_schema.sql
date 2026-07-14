-- Standalone bootstrap for a fresh Supabase project.  Earlier releases relied
-- on tables that happened to exist in the original project, which made a clean
-- `supabase db push` fail before reaching the persistent-backend migrations.

create extension if not exists pg_net with schema extensions;
create extension if not exists pg_cron with schema pg_catalog;
create extension if not exists pgcrypto with schema extensions;

create or replace function public.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at = clock_timestamp();
  return new;
end;
$$;

create table if not exists public.stock_master (
  symbol text primary key,
  name text not null,
  market text not null,
  industry text,
  security_type text not null default '股票',
  source text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.stock_snapshots (
  symbol text not null references public.stock_master(symbol) on delete cascade,
  trade_date date not null,
  close numeric,
  change_pct numeric,
  volume bigint,
  pe numeric,
  pb numeric,
  dividend_yield numeric,
  revenue_growth numeric,
  eps numeric,
  roe numeric,
  debt_ratio numeric,
  foreign_buy bigint,
  institutional_buy bigint,
  margin_change bigint,
  short_change bigint,
  is_disposition boolean not null default false,
  is_full_delivery boolean not null default false,
  raw_data jsonb not null default '{}'::jsonb,
  source text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (symbol, trade_date)
);
create index if not exists stock_snapshots_trade_date_idx
  on public.stock_snapshots (trade_date desc);

-- These two tables are part of the public market-data API.  Keep them
-- read-only at both the privilege and row-policy layers on a fresh project.
-- The policy guards also make this bootstrap safe when it is applied
-- out-of-order to the original project with `db push --include-all`.
alter table public.stock_master enable row level security;
alter table public.stock_snapshots enable row level security;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public'
      and tablename = 'stock_master'
      and policyname = 'stock_master_public_read'
  ) then
    create policy stock_master_public_read on public.stock_master
      for select to anon, authenticated using (true);
  end if;

  if not exists (
    select 1 from pg_policies
    where schemaname = 'public'
      and tablename = 'stock_snapshots'
      and policyname = 'stock_snapshots_public_read'
  ) then
    create policy stock_snapshots_public_read on public.stock_snapshots
      for select to anon, authenticated using (true);
  end if;
end
$$;

revoke all on public.stock_master, public.stock_snapshots from anon, authenticated;
grant select on public.stock_master, public.stock_snapshots to anon, authenticated;
grant all on public.stock_master, public.stock_snapshots to service_role;

create table if not exists public.prediction_logs (
  id uuid primary key default extensions.gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  symbol text not null,
  stock_name text,
  prediction_date date not null,
  horizon_days integer not null,
  reference_price numeric,
  predicted_direction text,
  up_probability numeric,
  neutral_probability numeric,
  down_probability numeric,
  confidence numeric,
  expected_low numeric,
  expected_high numeric,
  model_version text not null,
  factors jsonb not null default '{}'::jsonb,
  evaluated_at timestamptz,
  actual_price numeric,
  actual_return_pct numeric,
  actual_direction text,
  is_correct boolean,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, symbol, prediction_date, horizon_days, model_version)
);

create table if not exists public.investment_journal (
  id uuid primary key default extensions.gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  symbol text not null,
  stock_name text,
  entry_date date not null,
  action text not null,
  price numeric,
  quantity numeric,
  horizon text,
  thesis text,
  risk_plan text,
  target_plan text,
  emotion text,
  followed_plan boolean,
  exit_price numeric,
  exit_date date,
  return_pct numeric,
  result_note text,
  tags text[] not null default '{}',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.prediction_logs enable row level security;
alter table public.investment_journal enable row level security;

do $$
begin
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'prediction_logs' and policyname = 'prediction_logs_owner') then
    create policy prediction_logs_owner on public.prediction_logs
      for all to authenticated using ((select auth.uid()) = user_id)
      with check ((select auth.uid()) = user_id);
  end if;
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'investment_journal' and policyname = 'investment_journal_owner') then
    create policy investment_journal_owner on public.investment_journal
      for all to authenticated using ((select auth.uid()) = user_id)
      with check ((select auth.uid()) = user_id);
  end if;
end
$$;

grant select, insert, update, delete on public.prediction_logs, public.investment_journal to authenticated;

drop trigger if exists prediction_logs_set_updated_at on public.prediction_logs;
create trigger prediction_logs_set_updated_at before update on public.prediction_logs
for each row execute function public.set_updated_at();
drop trigger if exists investment_journal_set_updated_at on public.investment_journal;
create trigger investment_journal_set_updated_at before update on public.investment_journal
for each row execute function public.set_updated_at();

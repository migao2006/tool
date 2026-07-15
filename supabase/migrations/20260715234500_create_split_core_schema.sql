-- v18.0 core project baseline.
-- This migration is intentionally independent from the MARKET schema: it owns
-- only Auth-adjacent, per-user, and administrator-membership data.

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

create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text,
  display_name text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.prediction_logs (
  id uuid primary key default extensions.gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  symbol text not null check (symbol ~ '^[0-9]{4}$'),
  stock_name text,
  prediction_date date not null,
  horizon_days integer not null default 5 check (horizon_days between 1 and 60),
  reference_price numeric,
  predicted_direction text not null check (predicted_direction in ('up', 'neutral', 'down')),
  up_probability numeric check (up_probability between 0 and 100),
  neutral_probability numeric check (neutral_probability between 0 and 100),
  down_probability numeric check (down_probability between 0 and 100),
  confidence numeric check (confidence between 0 and 100),
  expected_low numeric,
  expected_high numeric,
  model_version text not null default 'v15-fixed-factor',
  factors jsonb not null default '{}'::jsonb,
  evaluated_at timestamptz,
  actual_price numeric,
  actual_return_pct numeric,
  actual_direction text check (actual_direction in ('up', 'neutral', 'down')),
  is_correct boolean,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, symbol, prediction_date, horizon_days, model_version)
);

create table public.investment_journal (
  id uuid primary key default extensions.gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  symbol text not null check (symbol ~ '^[0-9]{4}$'),
  stock_name text,
  entry_date date not null default current_date,
  action text not null default 'observe' check (action in ('observe', 'buy', 'sell', 'review')),
  price numeric,
  quantity numeric,
  horizon text check (horizon in ('short', 'swing', 'medium', 'long')),
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

create table public.watchlist_groups (
  id uuid primary key default extensions.gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  name text not null check (char_length(name) between 1 and 40),
  sort_order integer not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (id, user_id)
);

create table public.watchlist_items (
  id uuid primary key default extensions.gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  group_id uuid not null,
  symbol text not null check (char_length(symbol) between 2 and 12),
  added_price numeric,
  added_at timestamptz not null default now(),
  note text not null default '' check (char_length(note) <= 3000),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (group_id, symbol),
  constraint watchlist_items_group_user_fk
    foreign key (group_id, user_id)
    references public.watchlist_groups(id, user_id)
    on delete cascade
);

create table public.strategies (
  id uuid primary key default extensions.gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  name text not null check (char_length(name) between 1 and 80),
  original_text text not null default '',
  conditions jsonb not null default '{}'::jsonb,
  last_run_at timestamptz,
  last_result_count integer not null default 0 check (last_result_count >= 0),
  last_results text[] not null default '{}',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.app_admins (
  user_id uuid primary key references auth.users(id) on delete cascade,
  username text not null constraint app_admins_username_format
    check (username ~ '^[A-Za-z0-9_.-]{3,32}$'),
  active boolean not null default true,
  created_at timestamptz not null default clock_timestamp(),
  updated_at timestamptz not null default clock_timestamp()
);

create unique index app_admins_username_lower_uidx
  on public.app_admins ((lower(username)));
create index investment_journal_user_date_idx
  on public.investment_journal (user_id, entry_date desc);
create index watchlist_groups_user_sort_idx
  on public.watchlist_groups (user_id, sort_order, id);
create index watchlist_items_user_group_added_idx
  on public.watchlist_items (user_id, group_id, added_at desc);
create index strategies_user_idx
  on public.strategies (user_id, created_at desc);

alter table public.profiles enable row level security;
alter table public.prediction_logs enable row level security;
alter table public.investment_journal enable row level security;
alter table public.watchlist_groups enable row level security;
alter table public.watchlist_items enable row level security;
alter table public.strategies enable row level security;
alter table public.app_admins enable row level security;

create policy profiles_select_own on public.profiles
  for select to authenticated using ((select auth.uid()) = id);
create policy profiles_update_own on public.profiles
  for update to authenticated using ((select auth.uid()) = id)
  with check ((select auth.uid()) = id);
create policy prediction_logs_owner on public.prediction_logs
  for all to authenticated using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);
create policy investment_journal_owner on public.investment_journal
  for all to authenticated using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);
create policy watchlist_groups_select_own on public.watchlist_groups
  for select to authenticated using ((select auth.uid()) = user_id);
create policy watchlist_groups_insert_own on public.watchlist_groups
  for insert to authenticated with check ((select auth.uid()) = user_id);
create policy watchlist_groups_update_own on public.watchlist_groups
  for update to authenticated using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);
create policy watchlist_groups_delete_own on public.watchlist_groups
  for delete to authenticated using ((select auth.uid()) = user_id);
create policy watchlist_items_select_own on public.watchlist_items
  for select to authenticated using ((select auth.uid()) = user_id);
create policy watchlist_items_insert_own on public.watchlist_items
  for insert to authenticated with check ((select auth.uid()) = user_id);
create policy watchlist_items_update_own on public.watchlist_items
  for update to authenticated using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);
create policy watchlist_items_delete_own on public.watchlist_items
  for delete to authenticated using ((select auth.uid()) = user_id);
create policy strategies_select_own on public.strategies
  for select to authenticated using ((select auth.uid()) = user_id);
create policy strategies_insert_own on public.strategies
  for insert to authenticated with check ((select auth.uid()) = user_id);
create policy strategies_update_own on public.strategies
  for update to authenticated using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);
create policy strategies_delete_own on public.strategies
  for delete to authenticated using ((select auth.uid()) = user_id);
create policy app_admins_read_self on public.app_admins
  for select to authenticated using ((select auth.uid()) = user_id);

revoke all on table public.profiles, public.prediction_logs,
  public.investment_journal, public.watchlist_groups,
  public.watchlist_items, public.strategies, public.app_admins
  from public, anon, authenticated;
grant select, update on table public.profiles to authenticated;
grant select, insert, update, delete on table public.prediction_logs,
  public.investment_journal, public.watchlist_groups,
  public.watchlist_items, public.strategies to authenticated;
grant select on table public.app_admins to authenticated;
grant all on table public.profiles, public.prediction_logs,
  public.investment_journal, public.watchlist_groups,
  public.watchlist_items, public.strategies, public.app_admins to service_role;

create trigger profiles_set_updated_at before update on public.profiles
for each row execute function public.set_updated_at();
create trigger prediction_logs_set_updated_at before update on public.prediction_logs
for each row execute function public.set_updated_at();
create trigger investment_journal_set_updated_at before update on public.investment_journal
for each row execute function public.set_updated_at();
create trigger watchlist_groups_set_updated_at before update on public.watchlist_groups
for each row execute function public.set_updated_at();
create trigger watchlist_items_set_updated_at before update on public.watchlist_items
for each row execute function public.set_updated_at();
create trigger strategies_set_updated_at before update on public.strategies
for each row execute function public.set_updated_at();
create trigger app_admins_set_updated_at before update on public.app_admins
for each row execute function public.set_updated_at();

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.profiles (id, email, display_name)
  values (
    new.id,
    new.email,
    coalesce(new.raw_user_meta_data ->> 'display_name', split_part(coalesce(new.email, ''), '@', 1))
  )
  on conflict (id) do nothing;

  insert into public.watchlist_groups (user_id, name, sort_order)
  values (new.id, '我的自選', 0);
  return new;
end;
$$;

create trigger on_auth_user_created
after insert on auth.users
for each row execute function public.handle_new_user();

create or replace function public.twss_is_admin()
returns boolean
language sql
stable
security invoker
set search_path = ''
as $$
  select (select auth.uid()) is not null and exists (
    select 1 from public.app_admins a
    where a.user_id = (select auth.uid()) and a.active
  );
$$;

revoke all on function public.twss_is_admin() from public, anon, authenticated;
grant execute on function public.twss_is_admin() to authenticated, service_role;

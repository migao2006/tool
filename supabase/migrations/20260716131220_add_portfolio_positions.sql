-- CORE Supabase only: authenticated user-owned current positions.
create table public.portfolio_positions (
  id uuid primary key default extensions.gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  symbol text not null,
  stock_name text not null,
  quantity numeric(20, 4) not null,
  average_cost numeric(20, 4) not null,
  note text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint portfolio_positions_symbol_check
    check (symbol ~ '^[0-9A-Z]{2,12}$'),
  constraint portfolio_positions_stock_name_check
    check (char_length(stock_name) between 1 and 120),
  constraint portfolio_positions_quantity_check
    check (quantity > 0),
  constraint portfolio_positions_average_cost_check
    check (average_cost > 0),
  constraint portfolio_positions_note_check
    check (char_length(note) <= 1000),
  constraint portfolio_positions_user_symbol_key unique (user_id, symbol)
);

create index portfolio_positions_user_updated_idx
  on public.portfolio_positions (user_id, updated_at desc);

alter table public.portfolio_positions enable row level security;

create policy portfolio_positions_select_own
  on public.portfolio_positions
  for select to authenticated
  using ((select auth.uid()) = user_id);

create policy portfolio_positions_insert_own
  on public.portfolio_positions
  for insert to authenticated
  with check ((select auth.uid()) = user_id);

create policy portfolio_positions_update_own
  on public.portfolio_positions
  for update to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

create policy portfolio_positions_delete_own
  on public.portfolio_positions
  for delete to authenticated
  using ((select auth.uid()) = user_id);

revoke all on table public.portfolio_positions from public, anon, authenticated;
grant select, insert, update, delete on table public.portfolio_positions to authenticated;
grant all on table public.portfolio_positions to service_role;

create trigger portfolio_positions_set_updated_at
before update on public.portfolio_positions
for each row execute function public.set_updated_at();

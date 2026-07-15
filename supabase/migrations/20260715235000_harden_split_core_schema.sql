-- Close trigger-function RPC access and cover the composite watchlist FK.

revoke all on function public.handle_new_user()
  from public, anon, authenticated;

create index if not exists watchlist_items_group_user_idx
  on public.watchlist_items (group_id, user_id);

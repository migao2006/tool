-- Match the validated constraints on the legacy CORE tables before cutover.

alter table public.prediction_logs
  add constraint prediction_logs_symbol_check check (symbol ~ '^[0-9]{4}$'),
  add constraint prediction_logs_horizon_days_check check (horizon_days between 1 and 60),
  add constraint prediction_logs_predicted_direction_check check (predicted_direction in ('up', 'neutral', 'down')),
  add constraint prediction_logs_up_probability_check check (up_probability between 0 and 100),
  add constraint prediction_logs_neutral_probability_check check (neutral_probability between 0 and 100),
  add constraint prediction_logs_down_probability_check check (down_probability between 0 and 100),
  add constraint prediction_logs_confidence_check check (confidence between 0 and 100),
  add constraint prediction_logs_actual_direction_check check (actual_direction in ('up', 'neutral', 'down'));

alter table public.prediction_logs
  alter column horizon_days set default 5,
  alter column predicted_direction set not null,
  alter column model_version set default 'v15-fixed-factor';

alter table public.investment_journal
  add constraint investment_journal_symbol_check check (symbol ~ '^[0-9]{4}$'),
  add constraint investment_journal_action_check check (action in ('observe', 'buy', 'sell', 'review')),
  add constraint investment_journal_horizon_check check (horizon in ('short', 'swing', 'medium', 'long'));

alter table public.investment_journal
  alter column entry_date set default current_date,
  alter column action set default 'observe';

alter table public.watchlist_groups
  drop constraint watchlist_groups_name_check,
  add constraint watchlist_groups_name_check check (char_length(name) between 1 and 40);

alter table public.watchlist_items
  drop constraint watchlist_items_symbol_check,
  drop constraint watchlist_items_note_check,
  add constraint watchlist_items_symbol_check check (char_length(symbol) between 2 and 12),
  add constraint watchlist_items_note_check check (char_length(note) <= 3000);

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

revoke all on function public.handle_new_user()
  from public, anon, authenticated;

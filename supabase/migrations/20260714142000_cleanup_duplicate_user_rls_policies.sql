-- Earlier deployments created one policy per command before the consolidated,
-- authenticated-only owner policies were added.  Both sets enforce the same
-- user_id check, but permissive policies are evaluated together and the older
-- set calls auth.uid() once per row.  Keep the consolidated policies from the
-- base schema and remove only the redundant legacy names.

drop policy if exists prediction_logs_select_own on public.prediction_logs;
drop policy if exists prediction_logs_insert_own on public.prediction_logs;
drop policy if exists prediction_logs_update_own on public.prediction_logs;
drop policy if exists prediction_logs_delete_own on public.prediction_logs;

drop policy if exists investment_journal_select_own on public.investment_journal;
drop policy if exists investment_journal_insert_own on public.investment_journal;
drop policy if exists investment_journal_update_own on public.investment_journal;
drop policy if exists investment_journal_delete_own on public.investment_journal;

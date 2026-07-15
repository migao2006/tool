-- v17: remove the paid Gemini research branch and add free, database-only
-- health/ranking/peer context.  The quantitative scoring engine is unchanged.

-- AI cleanup is deliberately idempotent so this migration works both on the
-- existing production database and on a fresh project where the old AI
-- migrations are no longer present in source control.
do $$
declare
  existing_job bigint;
begin
  if to_regclass('cron.job') is not null then
    for existing_job in
      select jobid from cron.job where jobname = 'twss-ai-research-weekday'
    loop
      perform cron.unschedule(existing_job);
    end loop;
  end if;
end
$$;

drop function if exists public.twss_claim_manual_ai_request(text, text, text, text, text, integer, integer);
drop function if exists public.twss_finish_manual_ai_request(uuid, boolean, text);
drop function if exists public.twss_reserve_ai_calls(integer, integer);
drop function if exists public.twss_finish_ai_calls(integer, integer);
drop function if exists public.twss_get_gemini_api_key();

drop table if exists public.ai_stock_research cascade;
drop table if exists public.ai_research_runs cascade;
drop table if exists public.ai_research_usage cascade;

delete from public.stock_sync_state where job_key = 'ai_research';
delete from vault.secrets where name = 'twss_gemini_api_key';

-- Restore the shared retention function to its pre-AI responsibility.  Keep
-- the existing twss-prune-history cron job and every non-AI data table.
create or replace function public.twss_prune_history()
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  snapshot_rows integer := 0;
  price_rows integer := 0;
  flow_rows integer := 0;
  margin_rows integer := 0;
  score_rows integer := 0;
begin
  delete from public.stock_snapshots where trade_date < current_date - 60;
  get diagnostics snapshot_rows = row_count;

  delete from public.stock_price_history where trade_date < current_date - 550;
  get diagnostics price_rows = row_count;

  delete from public.stock_institutional_flows where trade_date < current_date - 180;
  get diagnostics flow_rows = row_count;

  delete from public.stock_margin_history where trade_date < current_date - 270;
  get diagnostics margin_rows = row_count;

  delete from public.opportunity_score_history where score_date < current_date - 730;
  get diagnostics score_rows = row_count;

  return pg_catalog.jsonb_build_object(
    'stock_snapshots', snapshot_rows,
    'stock_price_history', price_rows,
    'stock_institutional_flows', flow_rows,
    'stock_margin_history', margin_rows,
    'opportunity_score_history', score_rows,
    'pruned_at', clock_timestamp()
  );
end;
$$;

revoke all on function public.twss_prune_history() from public, anon, authenticated;
grant execute on function public.twss_prune_history() to service_role;

-- Fresh-project baseline for the existing cloud watchlist feature.  Production
-- already has these tables; IF NOT EXISTS keeps all current user rows intact.
create table if not exists public.watchlist_groups (
  id uuid primary key default extensions.gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  name text not null check (char_length(name) between 1 and 80),
  sort_order integer not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (id, user_id)
);

create table if not exists public.watchlist_items (
  id uuid primary key default extensions.gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  group_id uuid not null,
  symbol text not null check (symbol ~ '^[0-9]{4,6}[A-Za-z]?$'),
  added_price numeric,
  added_at timestamptz not null default now(),
  note text not null default '' check (char_length(note) <= 1000),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (group_id, symbol),
  constraint watchlist_items_group_user_fk
    foreign key (group_id, user_id)
    references public.watchlist_groups(id, user_id)
    on delete cascade
);

alter table public.watchlist_groups enable row level security;
alter table public.watchlist_items enable row level security;

do $$
begin
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='watchlist_groups' and policyname='watchlist_groups_select_own') then
    create policy watchlist_groups_select_own on public.watchlist_groups for select to authenticated using ((select auth.uid()) = user_id);
  end if;
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='watchlist_groups' and policyname='watchlist_groups_insert_own') then
    create policy watchlist_groups_insert_own on public.watchlist_groups for insert to authenticated with check ((select auth.uid()) = user_id);
  end if;
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='watchlist_groups' and policyname='watchlist_groups_update_own') then
    create policy watchlist_groups_update_own on public.watchlist_groups for update to authenticated using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
  end if;
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='watchlist_groups' and policyname='watchlist_groups_delete_own') then
    create policy watchlist_groups_delete_own on public.watchlist_groups for delete to authenticated using ((select auth.uid()) = user_id);
  end if;
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='watchlist_items' and policyname='watchlist_items_select_own') then
    create policy watchlist_items_select_own on public.watchlist_items for select to authenticated using ((select auth.uid()) = user_id);
  end if;
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='watchlist_items' and policyname='watchlist_items_insert_own') then
    create policy watchlist_items_insert_own on public.watchlist_items for insert to authenticated with check ((select auth.uid()) = user_id);
  end if;
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='watchlist_items' and policyname='watchlist_items_update_own') then
    create policy watchlist_items_update_own on public.watchlist_items for update to authenticated using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
  end if;
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='watchlist_items' and policyname='watchlist_items_delete_own') then
    create policy watchlist_items_delete_own on public.watchlist_items for delete to authenticated using ((select auth.uid()) = user_id);
  end if;
end
$$;

grant select, insert, update, delete on public.watchlist_groups, public.watchlist_items to authenticated;
grant all on public.watchlist_groups, public.watchlist_items to service_role;

-- A daily score date is not usable until the independent group cursor has
-- finished.  This prevents a six-row in-progress day from appearing as a real
-- rank change against a completed 280-row day.
create table if not exists public.opportunity_ranking_cycles (
  score_date date not null,
  model_version text not null,
  group_name text not null check (group_name in ('listed', 'otc', 'etf')),
  status text not null default 'building' check (status in ('building', 'final')),
  expected_count integer not null default 0 check (expected_count >= 0),
  scored_count integer not null default 0 check (scored_count >= 0),
  official_count integer not null default 0 check (official_count >= 0),
  started_at timestamptz not null default now(),
  finalized_at timestamptz,
  updated_at timestamptz not null default now(),
  primary key (score_date, model_version, group_name)
);

create index if not exists opportunity_score_history_symbol_date_idx
  on public.opportunity_score_history (symbol, model_version, score_date desc);
create index if not exists opportunity_score_history_group_date_score_idx
  on public.opportunity_score_history (group_name, model_version, score_date desc, official, score desc);

alter table public.opportunity_ranking_cycles enable row level security;
drop policy if exists opportunity_ranking_cycles_public_read on public.opportunity_ranking_cycles;
create policy opportunity_ranking_cycles_public_read on public.opportunity_ranking_cycles
  for select to anon, authenticated using (status = 'final');
revoke all on public.opportunity_ranking_cycles from anon, authenticated;
grant select on public.opportunity_ranking_cycles to anon, authenticated;
grant all on public.opportunity_ranking_cycles to service_role;

create or replace function public.twss_finalize_ranking_cycle(
  p_group_name text,
  p_score_date date,
  p_model_version text,
  p_expected_count integer default 0
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_scored integer := 0;
  v_official integer := 0;
begin
  if p_group_name not in ('listed', 'otc', 'etf')
    or p_score_date is null
    or nullif(trim(coalesce(p_model_version, '')), '') is null
  then
    raise exception 'invalid ranking cycle';
  end if;

  select count(*), count(*) filter (where official)
  into v_scored, v_official
  from public.opportunity_score_history
  where group_name = p_group_name
    and score_date = p_score_date
    and model_version = p_model_version;

  if v_scored = 0 then
    raise exception 'cannot finalize an empty ranking cycle';
  end if;

  insert into public.opportunity_ranking_cycles (
    score_date, model_version, group_name, status, expected_count,
    scored_count, official_count, finalized_at, updated_at
  ) values (
    p_score_date, p_model_version, p_group_name, 'final',
    greatest(coalesce(p_expected_count, 0), v_scored), v_scored, v_official,
    clock_timestamp(), clock_timestamp()
  )
  on conflict (score_date, model_version, group_name) do update
  set status = 'final',
      expected_count = greatest(excluded.expected_count, public.opportunity_ranking_cycles.expected_count),
      scored_count = excluded.scored_count,
      official_count = excluded.official_count,
      finalized_at = coalesce(public.opportunity_ranking_cycles.finalized_at, excluded.finalized_at),
      updated_at = clock_timestamp();

  return pg_catalog.jsonb_build_object(
    'group', p_group_name, 'scoreDate', p_score_date,
    'modelVersion', p_model_version, 'scored', v_scored,
    'official', v_official, 'status', 'final'
  );
end;
$$;

revoke all on function public.twss_finalize_ranking_cycle(text, date, text, integer) from public, anon, authenticated;
grant execute on function public.twss_finalize_ranking_cycle(text, date, text, integer) to service_role;

-- Backfill only cycles explicitly marked complete by the existing deep jobs.
do $$
declare
  item record;
begin
  for item in
    select group_name, cycle_date, total_items
    from public.stock_sync_state
    where job_key in ('deep_listed', 'deep_otc', 'deep_etf')
      and group_name in ('listed', 'otc', 'etf')
      and cycle_date is not null
      and details ->> 'completedCycleKey' like cycle_date::text || ':%'
  loop
    if exists (
      select 1 from public.opportunity_score_history
      where group_name = item.group_name and score_date = item.cycle_date and model_version = '16.3'
    ) then
      perform public.twss_finalize_ranking_cycle(item.group_name, item.cycle_date, '16.3', item.total_items);
    end if;
  end loop;
end
$$;

-- Internal helper used only by the safe public context function below.
create or replace function public.twss_peer_metric(
  p_group_name text,
  p_industry text,
  p_scope text,
  p_metric_key text,
  p_target numeric,
  p_higher_is_better boolean
)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
  with peer_values as (
    select case p_metric_key
      when 'score' then a.score
      when 'revenue_avg3' then nullif(a.analysis #>> '{revenue,avg3Yoy}', '')::numeric
      when 'revenue_acceleration' then nullif(a.analysis #>> '{revenue,acceleration3}', '')::numeric
      when 'operating_margin' then nullif(a.analysis #>> '{financial,operatingMargin}', '')::numeric
      when 'cash_conversion' then nullif(a.analysis #>> '{financial,cashConversion}', '')::numeric
      when 'institutional_intensity' then nullif(a.analysis #>> '{institutional,intensity5}', '')::numeric
      when 'relative_strength20' then nullif(a.analysis #>> '{price,relative20}', '')::numeric
      when 'volume_ratio' then nullif(a.analysis #>> '{price,volumeRatio}', '')::numeric
      when 'atr_pct' then nullif(a.analysis #>> '{price,atrPct}', '')::numeric
      when 'pe' then nullif(a.stock ->> 'pe', '')::numeric
      when 'premium_discount' then nullif(a.analysis #>> '{etf,premiumDiscount}', '')::numeric
      else null
    end as metric_value
    from public.stock_analysis_cache a
    where a.group_name = p_group_name
      and a.status = 'ready'
      and (p_scope = 'group_fallback' or a.stock ->> 'industry' = p_industry)
  ), summary as (
    select
      count(*) filter (where metric_value is not null) as available_count,
      percentile_cont(0.5) within group (order by metric_value)
        filter (where metric_value is not null) as median_value,
      count(*) filter (
        where metric_value is not null and p_target is not null
          and case when p_higher_is_better then metric_value <= p_target else metric_value >= p_target end
      ) as favorable_count
    from peer_values
  )
  select pg_catalog.jsonb_build_object(
    'key', p_metric_key,
    'value', p_target,
    'median', median_value,
    'percentile', case when p_target is null or available_count = 0 then null
      else round((favorable_count::numeric * 100) / available_count, 1) end,
    'availableCount', available_count,
    'higherIsBetter', p_higher_is_better
  )
  from summary;
$$;

revoke all on function public.twss_peer_metric(text, text, text, text, numeric, boolean) from public;
grant execute on function public.twss_peer_metric(text, text, text, text, numeric, boolean) to anon, authenticated, service_role;

create or replace function public.twss_get_stock_context(p_symbol text)
returns jsonb
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
  target public.stock_analysis_cache%rowtype;
  v_industry text;
  v_scope text;
  v_peer_count integer;
  v_metrics jsonb;
  v_series jsonb;
  v_final_dates integer;
begin
  if p_symbol !~ '^[0-9]{4,6}[A-Za-z]?$' then
    raise exception 'invalid symbol';
  end if;

  select * into target
  from public.stock_analysis_cache
  where symbol = p_symbol and status = 'ready'
  limit 1;

  if not found then
    return pg_catalog.jsonb_build_object('available', false, 'symbol', p_symbol);
  end if;

  v_industry := coalesce(target.stock ->> 'industry', '未分類');
  select count(*) into v_peer_count
  from public.stock_analysis_cache a
  where a.group_name = target.group_name and a.status = 'ready'
    and a.stock ->> 'industry' = v_industry;
  v_scope := case when v_peer_count >= 5 then 'industry' else 'group_fallback' end;
  if v_scope = 'group_fallback' then
    select count(*) into v_peer_count from public.stock_analysis_cache a
    where a.group_name = target.group_name and a.status = 'ready';
  end if;

  if target.group_name = 'etf' then
    v_metrics := pg_catalog.jsonb_build_array(
      public.twss_peer_metric(target.group_name, v_industry, v_scope, 'score', target.score, true),
      public.twss_peer_metric(target.group_name, v_industry, v_scope, 'relative_strength20', nullif(target.analysis #>> '{price,relative20}', '')::numeric, true),
      public.twss_peer_metric(target.group_name, v_industry, v_scope, 'volume_ratio', nullif(target.analysis #>> '{price,volumeRatio}', '')::numeric, true),
      public.twss_peer_metric(target.group_name, v_industry, v_scope, 'premium_discount', nullif(target.analysis #>> '{etf,premiumDiscount}', '')::numeric, false),
      public.twss_peer_metric(target.group_name, v_industry, v_scope, 'atr_pct', nullif(target.analysis #>> '{price,atrPct}', '')::numeric, false)
    );
  else
    v_metrics := pg_catalog.jsonb_build_array(
      public.twss_peer_metric(target.group_name, v_industry, v_scope, 'score', target.score, true),
      public.twss_peer_metric(target.group_name, v_industry, v_scope, 'revenue_avg3', nullif(target.analysis #>> '{revenue,avg3Yoy}', '')::numeric, true),
      public.twss_peer_metric(target.group_name, v_industry, v_scope, 'revenue_acceleration', nullif(target.analysis #>> '{revenue,acceleration3}', '')::numeric, true),
      public.twss_peer_metric(target.group_name, v_industry, v_scope, 'operating_margin', nullif(target.analysis #>> '{financial,operatingMargin}', '')::numeric, true),
      public.twss_peer_metric(target.group_name, v_industry, v_scope, 'cash_conversion', nullif(target.analysis #>> '{financial,cashConversion}', '')::numeric, true),
      public.twss_peer_metric(target.group_name, v_industry, v_scope, 'institutional_intensity', nullif(target.analysis #>> '{institutional,intensity5}', '')::numeric, true),
      public.twss_peer_metric(target.group_name, v_industry, v_scope, 'relative_strength20', nullif(target.analysis #>> '{price,relative20}', '')::numeric, true),
      public.twss_peer_metric(target.group_name, v_industry, v_scope, 'pe', nullif(target.stock ->> 'pe', '')::numeric, false)
    );
  end if;

  select count(*) into v_final_dates
  from public.opportunity_ranking_cycles
  where group_name = target.group_name and model_version = '16.3' and status = 'final';

  with ranked as (
    select h.symbol, h.score_date, h.score, h.confidence, h.official,
      rank() over (partition by h.score_date order by h.score desc nulls last, h.confidence desc) as rank_value
    from public.opportunity_score_history h
    join public.opportunity_ranking_cycles c
      on c.group_name = h.group_name and c.score_date = h.score_date
      and c.model_version = h.model_version and c.status = 'final'
    where h.group_name = target.group_name and h.model_version = '16.3' and h.official
  )
  select coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
    'date', score_date, 'score', score, 'confidence', confidence, 'rank', rank_value
  ) order by score_date), '[]'::jsonb)
  into v_series
  from (select * from ranked where symbol = p_symbol order by score_date desc limit 20) recent;

  return pg_catalog.jsonb_build_object(
    'available', true,
    'symbol', p_symbol,
    'group', target.group_name,
    'industry', v_industry,
    'peer', pg_catalog.jsonb_build_object(
      'scope', v_scope, 'peerCount', v_peer_count, 'metrics', v_metrics
    ),
    'trend', pg_catalog.jsonb_build_object(
      'status', case when v_final_dates >= 2 then 'ready' else 'accumulating' end,
      'finalDateCount', v_final_dates,
      'minimumFinalDates', 2,
      'series', v_series
    )
  );
end;
$$;

revoke all on function public.twss_get_stock_context(text) from public;
grant execute on function public.twss_get_stock_context(text) to anon, authenticated, service_role;

create or replace function public.twss_public_data_health()
returns jsonb
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
  universe record;
  v_groups jsonb;
  v_sources jsonb;
  v_repairs integer := 0;
  v_errors integer := 0;
  v_final_dates integer := 0;
  v_latest_final date;
  v_overall text;
begin
  select * into universe from public.stock_sync_state where job_key = 'universe' limit 1;

  select coalesce(pg_catalog.jsonb_object_agg(group_name, payload), '{}'::jsonb)
  into v_groups
  from (
    select s.group_name, pg_catalog.jsonb_build_object(
      'status', s.status,
      'dataDate', s.cycle_date,
      'eligible', s.total_items,
      'verified', s.processed_count,
      'official', (select count(*) from public.stock_analysis_cache a where a.group_name=s.group_name and a.status='ready' and a.official),
      'ratio', case when s.total_items > 0 then round(s.processed_count::numeric * 100 / s.total_items, 1) else 0 end,
      'lastSuccessAt', s.last_success_at,
      'nextRunAt', s.next_run_at,
      'lastError', s.last_error
    ) payload
    from public.stock_sync_state s
    where s.job_key in ('deep_listed', 'deep_otc', 'deep_etf')
  ) grouped;

  select count(*) filter (where needs_repair), count(*) filter (where status='error')
  into v_repairs, v_errors
  from public.stock_analysis_cache;

  select count(distinct score_date), max(score_date)
  into v_final_dates, v_latest_final
  from public.opportunity_ranking_cycles where status='final';

  v_sources := pg_catalog.jsonb_build_object(
    'price', pg_catalog.jsonb_build_object(
      'label', '每日行情', 'status', case when universe.details #>> '{sources,stocks,dates,price,latest}' is null then 'missing' else 'healthy' end,
      'latest', universe.details #>> '{sources,stocks,dates,price,latest}',
      'covered', coalesce((universe.details #>> '{sources,stocks,count}')::integer, 0),
      'reason', universe.details #>> '{sources,stocks,sourceStatus,price}'
    ),
    'revenue', pg_catalog.jsonb_build_object(
      'label', '月營收',
      'status', case when coalesce((universe.details #>> '{sources,revenue,rows}')::integer, 0) = 0 then 'missing'
        when coalesce((universe.details #>> '{sources,revenue,missingAmount}')::integer, 0) > 0 then 'partial' else 'healthy' end,
      'latest', universe.details #>> '{sources,revenue,period}',
      'covered', coalesce((universe.details #>> '{sources,revenue,matched}')::integer, 0),
      'missing', coalesce((universe.details #>> '{sources,revenue,missingAmount}')::integer, 0),
      'reason', universe.details #>> '{sources,revenue,sourceStatus,fallback}'
    ),
    'financial', pg_catalog.jsonb_build_object(
      'label', '季度財報', 'status', case when coalesce((universe.details #>> '{sources,financial,rows}')::integer, 0) = 0 then 'missing' else 'healthy' end,
      'latest', universe.details #>> '{sources,financial,period}',
      'covered', coalesce((universe.details #>> '{sources,financial,matched}')::integer, 0),
      'reason', universe.details #>> '{sources,financial,sourceStatus,fallback}'
    ),
    'institutional', pg_catalog.jsonb_build_object(
      'label', '法人籌碼', 'status', case when universe.details #>> '{sources,stocks,dates,institutional,latest}' is null then 'missing' else 'healthy' end,
      'latest', universe.details #>> '{sources,stocks,dates,institutional,latest}',
      'covered', coalesce((universe.details #>> '{sources,stocks,count}')::integer, 0),
      'reason', universe.details #>> '{sources,stocks,sourceStatus,institutional}'
    ),
    'margin', pg_catalog.jsonb_build_object(
      'label', '融資融券', 'status', case when universe.details #>> '{sources,stocks,dates,margin,latest}' is null then 'missing' else 'healthy' end,
      'latest', universe.details #>> '{sources,stocks,dates,margin,latest}',
      'covered', coalesce((universe.details #>> '{sources,stocks,count}')::integer, 0),
      'reason', universe.details #>> '{sources,stocks,sourceStatus,margin}'
    ),
    'holdings', pg_catalog.jsonb_build_object(
      'label', '集保持股', 'status', case when universe.details #>> '{sources,holdings,error}' is not null then 'error'
        when universe.details #>> '{sources,holdings,date}' is null then 'missing' else 'healthy' end,
      'latest', universe.details #>> '{sources,holdings,date}',
      'covered', coalesce((universe.details #>> '{sources,holdings,rows}')::integer, 0),
      'reason', universe.details #>> '{sources,holdings,error}'
    ),
    'benchmark', pg_catalog.jsonb_build_object(
      'label', '市場基準',
      'status', case when coalesce((universe.details #>> '{sources,benchmarks,coverage,listed}')::boolean, false)
        and coalesce((universe.details #>> '{sources,benchmarks,coverage,otc}')::boolean, false) then 'healthy' else 'partial' end,
      'latest', universe.cycle_date,
      'covered', (case when coalesce((universe.details #>> '{sources,benchmarks,coverage,listed}')::boolean, false) then 1 else 0 end
        + case when coalesce((universe.details #>> '{sources,benchmarks,coverage,otc}')::boolean, false) then 1 else 0 end),
      'total', 2,
      'reason', universe.details #>> '{sources,benchmarks,error}'
    )
  );

  v_overall := case
    when universe.status = 'error' or v_errors > 0 then 'error'
    when v_repairs > 0 or universe.status in ('partial', 'pending') then 'warning'
    else 'healthy'
  end;

  return pg_catalog.jsonb_build_object(
    'version', '17.0',
    'generatedAt', clock_timestamp(),
    'dataDate', universe.cycle_date,
    'overallStatus', v_overall,
    'sources', v_sources,
    'groups', v_groups,
    'repairQueue', pg_catalog.jsonb_build_object('pending', v_repairs, 'errors', v_errors),
    'scoreHistory', pg_catalog.jsonb_build_object(
      'status', case when v_final_dates >= 2 then 'ready' else 'accumulating' end,
      'finalDateCount', v_final_dates,
      'minimumFinalDates', 2,
      'latestFinalDate', v_latest_final
    ),
    'costPolicy', '只使用既有公開資料與資料庫計算，不呼叫付費 AI'
  );
end;
$$;

revoke all on function public.twss_public_data_health() from public;
grant execute on function public.twss_public_data_health() to anon, authenticated, service_role;

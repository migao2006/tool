-- v19 read models for fast public pages.  Existing market tables remain the
-- source of truth; these tables contain only reproducible, idempotent output.

create or replace function public.twss_v19_category_dimension(
  p_categories jsonb,
  p_keys text[],
  p_unavailable_reason text
)
returns jsonb
language sql
immutable
security invoker
set search_path = ''
as $$
  with selected as (
    select
      item ->> 'key' as key,
      (item ->> 'score')::numeric as score,
      greatest(0, coalesce((item ->> 'weight')::numeric, 1)) as weight
    from pg_catalog.jsonb_array_elements(coalesce(p_categories, '[]'::jsonb)) item
    where item ->> 'key' = any(p_keys)
      and pg_catalog.jsonb_typeof(item -> 'score') = 'number'
  ), aggregate_score as (
    select
      case when sum(weight) > 0
        then round(sum(score * weight) / sum(weight), 2)
        else null
      end as value,
      coalesce(pg_catalog.jsonb_agg(key order by key), '[]'::jsonb) as source_keys
    from selected
  )
  select pg_catalog.jsonb_build_object(
    'value', value,
    'sourceKeys', source_keys,
    'basis', 'v16.3-category-weighted-projection',
    'reason', case when value is null then p_unavailable_reason else null end
  )
  from aggregate_score;
$$;

create or replace function public.twss_v19_factor_dimension(
  p_categories jsonb,
  p_keys text[],
  p_unavailable_reason text
)
returns jsonb
language sql
immutable
security invoker
set search_path = ''
as $$
  with selected as (
    select
      factor ->> 'key' as key,
      (factor ->> 'score')::numeric as score,
      greatest(0, coalesce((factor ->> 'weight')::numeric, 1)) as weight
    from pg_catalog.jsonb_array_elements(coalesce(p_categories, '[]'::jsonb)) category
    cross join lateral pg_catalog.jsonb_array_elements(
      case when pg_catalog.jsonb_typeof(category -> 'items') = 'array'
        then category -> 'items' else '[]'::jsonb end
    ) factor
    where factor ->> 'key' = any(p_keys)
      and pg_catalog.jsonb_typeof(factor -> 'score') = 'number'
  ), aggregate_score as (
    select
      case when sum(weight) > 0
        then round(sum(score * weight) / sum(weight), 2)
        else null
      end as value,
      coalesce(pg_catalog.jsonb_agg(key order by key), '[]'::jsonb) as source_keys
    from selected
  )
  select pg_catalog.jsonb_build_object(
    'value', value,
    'sourceKeys', source_keys,
    'basis', 'v16.3-factor-weighted-projection',
    'reason', case when value is null then p_unavailable_reason else null end
  )
  from aggregate_score;
$$;

create or replace function public.twss_v19_score_dimensions(
  p_score numeric,
  p_confidence numeric,
  p_categories jsonb,
  p_risk jsonb,
  p_result jsonb
)
returns jsonb
language sql
immutable
security invoker
set search_path = ''
as $$
  select pg_catalog.jsonb_build_object(
    'overall', pg_catalog.jsonb_build_object(
      'value', p_score,
      'basis', 'v16.3-fixed-weight-composite',
      'reason', case when p_score is null then 'composite_unavailable' else null end
    ),
    'fundamental', public.twss_v19_category_dimension(
      p_categories, array['growth', 'valuation', 'structure', 'tracking'],
      'fundamental_categories_unavailable'
    ),
    'technical', public.twss_v19_category_dimension(
      p_categories, array['technical', 'trend'], 'technical_category_unavailable'
    ),
    'institutional', public.twss_v19_category_dimension(
      p_categories, array['chip'], 'institutional_category_not_applicable_or_unavailable'
    ),
    'volumeMomentum', public.twss_v19_factor_dimension(
      p_categories, array['volume', 'volume_structure', 'relative20', 'breakout'],
      'volume_momentum_factors_unavailable'
    ),
    'news', pg_catalog.jsonb_build_object(
      'value', null,
      'basis', 'not-used-by-v16.3-model',
      'reason', 'official_news_not_scored_by_v16.3'
    ),
    'risk', pg_catalog.jsonb_build_object(
      'value', case when pg_catalog.jsonb_typeof(p_risk -> 'deduction') = 'number'
        then greatest(0, 100 - least(100, (p_risk ->> 'deduction')::numeric))
        else null end,
      'severity', case when pg_catalog.jsonb_typeof(p_risk -> 'deduction') = 'number'
        then greatest(0, least(100, (p_risk ->> 'deduction')::numeric))
        else null end,
      'basis', 'v16.3-risk-deduction-inverse',
      'reason', case when pg_catalog.jsonb_typeof(p_risk -> 'deduction') is distinct from 'number'
        then 'risk_deduction_unavailable' else null end
    ),
    'confidence', pg_catalog.jsonb_build_object(
      'value', p_confidence,
      'basis', 'v16.3-source-coverage-confidence',
      'reason', case when p_confidence is null then 'confidence_unavailable' else null end
    ),
    'completeness', pg_catalog.jsonb_build_object(
      'value', case when pg_catalog.jsonb_typeof(p_result -> 'historyCoverage') = 'number'
        then (p_result ->> 'historyCoverage')::numeric else null end,
      'basis', 'v16.3-history-coverage',
      'reason', case when pg_catalog.jsonb_typeof(p_result -> 'historyCoverage') is distinct from 'number'
        then 'history_coverage_unavailable' else null end
    )
  );
$$;

revoke all on function public.twss_v19_category_dimension(jsonb, text[], text),
  public.twss_v19_factor_dimension(jsonb, text[], text),
  public.twss_v19_score_dimensions(numeric, numeric, jsonb, jsonb, jsonb)
  from public, anon, authenticated;
grant execute on function public.twss_v19_category_dimension(jsonb, text[], text),
  public.twss_v19_factor_dimension(jsonb, text[], text),
  public.twss_v19_score_dimensions(numeric, numeric, jsonb, jsonb, jsonb)
  to service_role;

create table if not exists public.v19_ranking_snapshots (
  symbol text not null references public.stock_master(symbol) on delete cascade,
  score_date date not null,
  model_version text not null,
  group_name text not null check (group_name in ('listed', 'otc', 'etf')),
  cycle_status text not null check (cycle_status in ('final', 'provisional')),
  rank_position integer check (rank_position > 0),
  previous_rank integer check (previous_rank > 0),
  rank_delta integer,
  score numeric,
  previous_score numeric,
  score_delta numeric,
  confidence numeric not null default 0 check (confidence between 0 and 100),
  official boolean not null default false,
  tier text,
  name text not null,
  market text,
  industry text,
  instrument_type text,
  stock_summary jsonb not null default '{}'::jsonb,
  result_summary jsonb not null default '{}'::jsonb,
  score_dimensions jsonb not null default '{}'::jsonb,
  risk_score numeric check (risk_score between 0 and 100),
  ai_score numeric check (ai_score between 0 and 100),
  ai_score_basis text not null default 'v16.3-fixed-weight-composite',
  trade_date date,
  source_fetched_at timestamptz,
  source_updated_at timestamptz,
  generated_at timestamptz not null default clock_timestamp(),
  primary key (symbol, score_date, model_version),
  foreign key (symbol, score_date, model_version)
    references public.opportunity_score_history(symbol, score_date, model_version)
    on delete cascade
);

create index if not exists v19_ranking_snapshots_group_rank_idx
  on public.v19_ranking_snapshots
    (group_name, model_version, score_date desc, rank_position asc nulls last)
  include (symbol, score, confidence, official, ai_score);
create index if not exists v19_ranking_snapshots_score_idx
  on public.v19_ranking_snapshots
    (model_version, score_date desc, score desc nulls last, confidence desc, symbol);
create index if not exists v19_ranking_snapshots_industry_idx
  on public.v19_ranking_snapshots
    (group_name, lower(industry), model_version, score_date desc);

comment on column public.v19_ranking_snapshots.ai_score is
  'Alias of the frozen v16.3 fixed-weight composite. Confidence remains separate and ranking is unchanged.';

alter table public.v19_ranking_snapshots enable row level security;
drop policy if exists v19_ranking_snapshots_public_read on public.v19_ranking_snapshots;
create policy v19_ranking_snapshots_public_read
  on public.v19_ranking_snapshots for select to anon, authenticated using (true);

revoke all on table public.v19_ranking_snapshots from public, anon, authenticated;
grant select on table public.v19_ranking_snapshots to anon, authenticated;
grant all on table public.v19_ranking_snapshots to service_role;

create or replace function public.twss_v19_refresh_ranking_snapshot(
  p_group_name text,
  p_score_date date,
  p_model_version text default '16.3',
  p_allow_provisional boolean default false
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_previous_date date;
  v_rows integer := 0;
  v_cycle_status text;
begin
  if p_group_name not in ('listed', 'otc', 'etf')
    or p_score_date is null
    or nullif(pg_catalog.btrim(coalesce(p_model_version, '')), '') is null
  then
    raise exception 'v19_snapshot_invalid_cycle';
  end if;

  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(
      'twss-v19:' || p_group_name || ':' || p_score_date::text || ':' || p_model_version,
      0
    )
  );

  if exists (
    select 1
    from public.opportunity_ranking_cycles c
    where c.group_name = p_group_name
      and c.score_date = p_score_date
      and c.model_version = p_model_version
      and c.status = 'final'
  ) then
    v_cycle_status := 'final';
  elsif p_allow_provisional and exists (
    select 1
    from public.opportunity_score_history h
    where h.group_name = p_group_name
      and h.score_date = p_score_date
      and h.model_version = p_model_version
  ) then
    v_cycle_status := 'provisional';
  else
    raise exception 'v19_snapshot_cycle_not_final';
  end if;

  select max(h.score_date)
  into v_previous_date
  from public.opportunity_score_history h
  where h.group_name = p_group_name
    and h.model_version = p_model_version
    and h.score_date < p_score_date;

  with current_scores as (
    select h.*
    from public.opportunity_score_history h
    where h.group_name = p_group_name
      and h.score_date = p_score_date
      and h.model_version = p_model_version
  ), current_official_ranks as (
    select
      h.symbol,
      row_number() over (
        order by h.score desc nulls last, h.confidence desc nulls last, h.symbol
      )::integer as rank_position
    from current_scores h
    where h.official
  ), current_ranked as (
    select h.*, r.rank_position
    from current_scores h
    left join current_official_ranks r on r.symbol = h.symbol
  ), previous_scores as (
    select h.symbol, h.score, h.confidence, h.official
    from public.opportunity_score_history h
    where h.group_name = p_group_name
      and h.score_date = v_previous_date
      and h.model_version = p_model_version
  ), previous_official_ranks as (
    select
      h.symbol,
      row_number() over (
        order by h.score desc nulls last, h.confidence desc nulls last, h.symbol
      )::integer as rank_position
    from previous_scores h
    where h.official
  ), previous_ranked as (
    select h.symbol, h.score, r.rank_position
    from previous_scores h
    left join previous_official_ranks r on r.symbol = h.symbol
  )
  insert into public.v19_ranking_snapshots (
    symbol, score_date, model_version, group_name, cycle_status, rank_position,
    previous_rank, rank_delta, score, previous_score, score_delta,
    confidence, official, tier, name, market, industry, instrument_type,
    stock_summary, result_summary, score_dimensions, risk_score,
    ai_score, ai_score_basis, trade_date, source_fetched_at,
    source_updated_at, generated_at
  )
  select
    h.symbol,
    h.score_date,
    h.model_version,
    h.group_name,
    v_cycle_status,
    h.rank_position,
    p.rank_position,
    case when h.rank_position is not null and p.rank_position is not null
      then p.rank_position - h.rank_position else null end,
    h.score,
    p.score,
    case when h.score is not null and p.score is not null
      then round((h.score - p.score)::numeric, 4) else null end,
    h.confidence,
    h.official,
    h.tier,
    coalesce(nullif(a.stock ->> 'name', ''), m.name, h.symbol),
    coalesce(nullif(a.stock ->> 'market', ''), m.market),
    coalesce(nullif(a.stock ->> 'industry', ''), m.industry),
    coalesce(nullif(a.stock ->> 'instrumentType', ''), m.security_type),
    coalesce(a.stock, '{}'::jsonb) || pg_catalog.jsonb_strip_nulls(
      pg_catalog.jsonb_build_object(
        'symbol', h.symbol,
        'name', coalesce(nullif(a.stock ->> 'name', ''), m.name, h.symbol),
        'market', coalesce(nullif(a.stock ->> 'market', ''), m.market),
        'industry', coalesce(nullif(a.stock ->> 'industry', ''), m.industry),
        'instrumentType', coalesce(nullif(a.stock ->> 'instrumentType', ''), m.security_type)
      )
    ),
    pg_catalog.jsonb_strip_nulls(pg_catalog.jsonb_build_object(
      'symbol', h.symbol,
      'name', coalesce(h.result ->> 'name', a.stock ->> 'name', m.name),
      'group', h.group_name,
      'score', h.score,
      'baseScore', h.result -> 'baseScore',
      'confidence', h.confidence,
      'official', h.official,
      'tier', h.tier,
      'categories', h.categories,
      'risk', h.risk,
      'archetypes', h.result -> 'archetypes',
      'reasons', h.result -> 'reasons',
      'missing', h.result -> 'missing'
    )),
    public.twss_v19_score_dimensions(
      h.score, h.confidence, h.categories, h.risk, h.result
    ),
    case when pg_catalog.jsonb_typeof(h.risk -> 'deduction') = 'number'
      then greatest(0, least(100, (h.risk ->> 'deduction')::numeric))
      else null end,
    h.score,
    'v16.3-fixed-weight-composite',
    case when coalesce(a.stock ->> 'priceDate', '') ~ '^\d{4}-\d{2}-\d{2}$'
      then (a.stock ->> 'priceDate')::date else null end,
    a.fetched_at,
    a.updated_at,
    clock_timestamp()
  from current_ranked h
  join public.stock_master m on m.symbol = h.symbol
  left join public.stock_analysis_cache a
    on a.symbol = h.symbol
    and a.data_date = h.score_date
    and a.analysis_version = '16.3-ultimate-data-audit'
    and a.status = 'ready'
  left join previous_ranked p on p.symbol = h.symbol
  on conflict (symbol, score_date, model_version) do update
  set group_name = excluded.group_name,
      cycle_status = excluded.cycle_status,
      rank_position = excluded.rank_position,
      previous_rank = excluded.previous_rank,
      rank_delta = excluded.rank_delta,
      score = excluded.score,
      previous_score = excluded.previous_score,
      score_delta = excluded.score_delta,
      confidence = excluded.confidence,
      official = excluded.official,
      tier = excluded.tier,
      name = excluded.name,
      market = excluded.market,
      industry = excluded.industry,
      instrument_type = excluded.instrument_type,
      stock_summary = excluded.stock_summary,
      result_summary = excluded.result_summary,
      score_dimensions = excluded.score_dimensions,
      risk_score = excluded.risk_score,
      ai_score = excluded.ai_score,
      ai_score_basis = excluded.ai_score_basis,
      trade_date = excluded.trade_date,
      source_fetched_at = excluded.source_fetched_at,
      source_updated_at = excluded.source_updated_at,
      generated_at = excluded.generated_at;

  delete from public.v19_ranking_snapshots s
  where s.group_name = p_group_name
    and s.score_date = p_score_date
    and s.model_version = p_model_version
    and not exists (
      select 1
      from public.opportunity_score_history h
      where h.symbol = s.symbol
        and h.score_date = s.score_date
        and h.model_version = s.model_version
    );

  select count(*)::integer
  into v_rows
  from public.v19_ranking_snapshots s
  where s.group_name = p_group_name
    and s.score_date = p_score_date
    and s.model_version = p_model_version;

  return pg_catalog.jsonb_build_object(
    'status', 'ready',
    'group', p_group_name,
    'scoreDate', p_score_date,
    'modelVersion', p_model_version,
    'cycleStatus', v_cycle_status,
    'rows', v_rows,
    'generatedAt', clock_timestamp()
  );
end;
$$;

revoke all on function public.twss_v19_refresh_ranking_snapshot(text, date, text, boolean)
  from public, anon, authenticated;
grant execute on function public.twss_v19_refresh_ranking_snapshot(text, date, text, boolean)
  to service_role;

create or replace function public.twss_v19_refresh_final_cycle()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if new.status = 'final' then
    begin
      perform public.twss_v19_refresh_ranking_snapshot(
        new.group_name,
        new.score_date,
        new.model_version,
        false
      );
    exception when others then
      -- Snapshot generation is an observation layer.  It must never roll back
      -- a completed immutable ranking cycle.
      raise warning 'v19_snapshot_refresh_failed group=% date=%',
        new.group_name, new.score_date;
    end;
  end if;
  return new;
end;
$$;

revoke all on function public.twss_v19_refresh_final_cycle()
  from public, anon, authenticated;
grant execute on function public.twss_v19_refresh_final_cycle() to service_role;

drop trigger if exists opportunity_ranking_cycles_v19_snapshot
  on public.opportunity_ranking_cycles;
create trigger opportunity_ranking_cycles_v19_snapshot
after insert or update of status, scored_count, official_count
on public.opportunity_ranking_cycles
for each row
when (new.status = 'final')
execute function public.twss_v19_refresh_final_cycle();

-- Bounded deterministic page RPC.  The cursor carries group_dates from the
-- first page, keeping subsequent pages on the same snapshot even if a newer
-- cycle is generated between requests.  row_number plus symbol tie-breaking
-- prevents equal scores from being skipped.
create or replace function public.twss_v19_rankings_page(
  p_group_name text default null,
  p_industry text default null,
  p_search text default null,
  p_sort text default 'score_desc',
  p_after_row integer default 0,
  p_limit integer default 10,
  p_model_version text default '16.3',
  p_group_dates jsonb default null
)
returns jsonb
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
  result jsonb;
begin
  if p_group_name is not null and p_group_name not in ('listed', 'otc', 'etf') then
    raise exception 'v19_page_invalid_group';
  end if;
  if char_length(coalesce(p_industry, '')) > 80
    or char_length(coalesce(p_search, '')) > 60
    or char_length(coalesce(p_model_version, '')) > 40
    or char_length(coalesce(p_group_dates::text, '')) > 256
  then
    raise exception 'v19_page_input_too_long';
  end if;
  if p_limit is null or p_limit < 1 or p_limit > 100
    or p_after_row is null or p_after_row < 0 or p_after_row > 1000000
  then
    raise exception 'v19_page_invalid_bounds';
  end if;
  if p_sort not in (
    'score_desc', 'score_asc', 'confidence_desc', 'updated_desc',
    'change_desc', 'risk_asc', 'risk_desc'
  ) then
    raise exception 'v19_page_invalid_sort';
  end if;

  with groups(group_name) as (
    values ('listed'::text), ('otc'::text), ('etf'::text)
  ), latest as (
    select
      g.group_name,
      coalesce(
        case
          when coalesce(p_group_dates ->> g.group_name, '') ~ '^\d{4}-\d{2}-\d{2}$'
          then (p_group_dates ->> g.group_name)::date
          else null
        end,
        (
          select max(recent.score_date)
          from public.v19_ranking_snapshots recent
          where recent.group_name = g.group_name
            and recent.model_version = p_model_version
        )
      ) as score_date
    from groups g
    where p_group_name is null or g.group_name = p_group_name
  ), industry_options as (
    select distinct pg_catalog.btrim(s.industry) as industry
    from public.v19_ranking_snapshots s
    join latest l
      on l.group_name = s.group_name
      and l.score_date = s.score_date
    where s.model_version = p_model_version
      and s.official
      and nullif(pg_catalog.btrim(coalesce(s.industry, '')), '') is not null
  ), filtered as (
    select s.*
    from public.v19_ranking_snapshots s
    join latest l
      on l.group_name = s.group_name
      and l.score_date = s.score_date
    where s.model_version = p_model_version
      and s.official
      and (nullif(pg_catalog.btrim(coalesce(p_industry, '')), '') is null
        or lower(coalesce(s.industry, '')) = lower(pg_catalog.btrim(p_industry)))
      and (nullif(pg_catalog.btrim(coalesce(p_search, '')), '') is null
        or position(lower(pg_catalog.btrim(p_search)) in lower(
          s.symbol || ' ' || s.name || ' ' || coalesce(s.industry, '')
        )) > 0)
  ), numbered as (
    select
      f.*,
      row_number() over (order by
        case when p_sort = 'score_desc' then f.score end desc nulls last,
        case when p_sort = 'score_asc' then f.score end asc nulls last,
        case when p_sort in ('score_desc', 'score_asc') then f.confidence end desc nulls last,
        case when p_sort = 'confidence_desc' then f.confidence end desc nulls last,
        case when p_sort = 'updated_desc' then f.source_updated_at end desc nulls last,
        case when p_sort = 'change_desc' then f.score_delta end desc nulls last,
        case when p_sort = 'risk_asc' then f.risk_score end asc nulls last,
        case when p_sort = 'risk_desc' then f.risk_score end desc nulls last,
        f.group_name,
        f.symbol
      )::integer as page_row,
      count(*) over ()::integer as total_count
    from filtered f
  ), page as (
    select n.*
    from numbered n
    where n.page_row > greatest(0, coalesce(p_after_row, 0))
      and n.page_row <= p_after_row + p_limit
    order by n.page_row
  ), statuses as (
    select
      l.group_name,
      l.score_date,
      coalesce(
        (
          select case when bool_and(s.cycle_status = 'final') then 'final' else 'provisional' end
          from public.v19_ranking_snapshots s
          where s.group_name = l.group_name
            and s.model_version = p_model_version
            and s.score_date = l.score_date
        ),
        'unavailable'
      ) as cycle_status
    from latest l
    where l.score_date is not null
  )
  select pg_catalog.jsonb_build_object(
    'group_dates', coalesce(
      (select pg_catalog.jsonb_object_agg(s.group_name, s.score_date) from statuses s),
      '{}'::jsonb
    ),
    'group_statuses', coalesce(
      (select pg_catalog.jsonb_object_agg(s.group_name, s.cycle_status) from statuses s),
      '{}'::jsonb
    ),
    'industries', coalesce(
      (select pg_catalog.jsonb_agg(i.industry order by i.industry) from industry_options i),
      '[]'::jsonb
    ),
    'items', coalesce(
      (select pg_catalog.jsonb_agg(to_jsonb(p) order by p.page_row) from page p),
      '[]'::jsonb
    ),
    'total', coalesce((select max(n.total_count) from numbered n), 0),
    'after_row', greatest(0, coalesce(p_after_row, 0)),
    'last_row', coalesce((select max(p.page_row) from page p), greatest(0, coalesce(p_after_row, 0))),
    'has_more', coalesce((select max(p.page_row) from page p), 0)
      < coalesce((select max(n.total_count) from numbered n), 0),
    'snapshot_generated_at', (select max(n.generated_at) from numbered n),
    'page_updated_at', pg_catalog.statement_timestamp()
  ) into result;

  return result;
end;
$$;

revoke all on function public.twss_v19_rankings_page(
  text, text, text, text, integer, integer, text, jsonb
) from public, anon, authenticated;
grant execute on function public.twss_v19_rankings_page(
  text, text, text, text, integer, integer, text, jsonb
) to anon, authenticated, service_role;

create table if not exists public.v19_news_items (
  id uuid primary key default extensions.gen_random_uuid(),
  source text not null,
  external_id text not null,
  market text not null check (market in ('listed', 'otc')),
  symbols text[] not null default '{}',
  company_name text,
  title text not null,
  summary text not null default '',
  category text,
  event_date date,
  sentiment_label text not null default 'neutral'
    check (sentiment_label in ('benefit', 'harm', 'neutral')),
  sentiment_score numeric not null default 0 check (sentiment_score between -100 and 100),
  sentiment_basis text not null default 'official-disclosure-keyword-rule-v1',
  sentiment_terms text[] not null default '{}',
  source_url text not null,
  published_at timestamptz not null,
  content_hash text not null,
  fetched_at timestamptz not null default clock_timestamp(),
  updated_at timestamptz not null default clock_timestamp(),
  unique (source, external_id)
);

create index if not exists v19_news_items_published_idx
  on public.v19_news_items (published_at desc, id);
create index if not exists v19_news_items_symbols_idx
  on public.v19_news_items using gin (symbols);
create index if not exists v19_news_items_market_published_idx
  on public.v19_news_items (market, published_at desc);

alter table public.v19_news_items enable row level security;
drop policy if exists v19_news_items_public_read on public.v19_news_items;
create policy v19_news_items_public_read
  on public.v19_news_items for select to anon, authenticated
  using (published_at <= clock_timestamp());

revoke all on table public.v19_news_items from public, anon, authenticated;
grant select (
  id, source, market, symbols, company_name, title, summary, category,
  event_date, sentiment_label, sentiment_score, sentiment_basis,
  sentiment_terms, source_url, published_at, fetched_at, updated_at
) on table public.v19_news_items to anon, authenticated;
grant all on table public.v19_news_items to service_role;

insert into public.stock_sync_state (job_key, group_name, details)
values
  ('v19_news', null, pg_catalog.jsonb_build_object('version', '19.0')),
  ('v19_rankings', null, pg_catalog.jsonb_build_object('version', '19.0'))
on conflict (job_key) do nothing;

-- Public job state deliberately excludes errors, leases, URLs and arbitrary
-- details.  Internal diagnostics remain service-role only.
create or replace function public.twss_v19_public_job_status()
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
  select coalesce(pg_catalog.jsonb_agg(
    pg_catalog.jsonb_build_object(
      'job', s.job_key,
      'group', s.group_name,
      'status', case
        when s.status in ('pending', 'running', 'success', 'partial', 'error')
          then s.status
        else 'pending'
      end,
      'cycleDate', s.cycle_date,
      'processed', greatest(0, s.processed_count),
      'total', greatest(0, s.total_items),
      'progress', case when s.total_items > 0 then
        least(100, round(100.0 * s.processed_count / s.total_items, 1))
        else case when s.status = 'success' then 100 else 0 end
      end,
      'lastSuccessAt', s.last_success_at,
      'updatedAt', s.updated_at
    ) order by
      case s.job_key
        when 'universe' then 1
        when 'deep_listed' then 2
        when 'deep_otc' then 3
        when 'deep_etf' then 4
        when 'v19_rankings' then 5
        when 'v19_news' then 6
        else 99
      end
  ), '[]'::jsonb)
  from public.stock_sync_state s
  where s.job_key in (
    'universe', 'deep_listed', 'deep_otc', 'deep_etf',
    'v19_rankings', 'v19_news'
  );
$$;

revoke all on function public.twss_v19_public_job_status()
  from public, anon, authenticated;
grant execute on function public.twss_v19_public_job_status()
  to anon, authenticated, service_role;

-- Refresh the newest available score history for every group.  A date without
-- a completed cycle is stored as provisional and remains visibly marked as
-- such; the final-cycle trigger upgrades the same idempotent rows to final.
create or replace function public.twss_v19_refresh_available_rankings()
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  group_item text;
  latest_date date;
  v_cycle_date date;
  desired_status text;
  history_count integer;
  snapshot_count integer;
  v_processed_count integer := 0;
  v_total_count integer := 0;
  refreshed_groups integer := 0;
  skipped_groups integer := 0;
  failed_groups integer := 0;
  history_max_created_at timestamptz;
  snapshot_max_generated_at timestamptz;
  snapshot_status_matches boolean;
  refresh_result jsonb;
  results jsonb := '{}'::jsonb;
begin
  update public.stock_sync_state
  set status = 'running',
      started_at = clock_timestamp(),
      processed_count = 0,
      total_items = 0,
      last_error = null,
      updated_at = clock_timestamp()
  where job_key = 'v19_rankings';

  foreach group_item in array array['listed', 'otc', 'etf']::text[]
  loop
    select max(h.score_date)
    into latest_date
    from public.opportunity_score_history h
    where h.group_name = group_item and h.model_version = '16.3';

    if latest_date is not null then
      if v_cycle_date is null or latest_date > v_cycle_date then
        v_cycle_date := latest_date;
      end if;

      begin
        select count(*)::integer, max(h.created_at)
        into history_count, history_max_created_at
        from public.opportunity_score_history h
        where h.group_name = group_item
          and h.score_date = latest_date
          and h.model_version = '16.3';

        desired_status := case when exists (
          select 1
          from public.opportunity_ranking_cycles c
          where c.group_name = group_item
            and c.score_date = latest_date
            and c.model_version = '16.3'
            and c.status = 'final'
        ) then 'final' else 'provisional' end;

        select
          count(*)::integer,
          max(s.generated_at),
          coalesce(bool_and(s.cycle_status = desired_status), false)
        into snapshot_count, snapshot_max_generated_at, snapshot_status_matches
        from public.v19_ranking_snapshots s
        where s.group_name = group_item
          and s.score_date = latest_date
          and s.model_version = '16.3';

        v_total_count := v_total_count + history_count;
        if snapshot_count = history_count
          and snapshot_status_matches
          and snapshot_max_generated_at >= history_max_created_at
        then
          skipped_groups := skipped_groups + 1;
          v_processed_count := v_processed_count + history_count;
          results := results || pg_catalog.jsonb_build_object(
            group_item,
            pg_catalog.jsonb_build_object(
              'status', 'unchanged',
              'cycleStatus', desired_status,
              'scoreDate', latest_date,
              'rows', history_count
            )
          );
        else
          refresh_result := public.twss_v19_refresh_ranking_snapshot(
            group_item, latest_date, '16.3', true
          );
          refreshed_groups := refreshed_groups + 1;
          v_processed_count := v_processed_count + history_count;
          results := results || pg_catalog.jsonb_build_object(group_item, refresh_result);
        end if;
      exception when others then
        failed_groups := failed_groups + 1;
        results := results || pg_catalog.jsonb_build_object(
          group_item,
          pg_catalog.jsonb_build_object('status', 'unavailable', 'scoreDate', latest_date)
        );
        raise warning 'v19_available_snapshot_failed group=% date=%', group_item, latest_date;
      end;
    else
      results := results || pg_catalog.jsonb_build_object(
        group_item,
        pg_catalog.jsonb_build_object('status', 'empty')
      );
    end if;
  end loop;

  update public.stock_sync_state
  set status = case when failed_groups > 0 then 'partial' else 'success' end,
      cycle_date = v_cycle_date,
      processed_count = v_processed_count,
      total_items = v_total_count,
      last_success_at = clock_timestamp(),
      last_error = null,
      details = pg_catalog.jsonb_build_object(
        'version', '19.0',
        'refreshedGroups', refreshed_groups,
        'unchangedGroups', skipped_groups,
        'failedGroups', failed_groups
      ),
      updated_at = clock_timestamp()
  where job_key = 'v19_rankings';

  return pg_catalog.jsonb_build_object(
    'version', '19.0',
    'groups', results,
    'refreshedGroups', refreshed_groups,
    'unchangedGroups', skipped_groups,
    'failedGroups', failed_groups,
    'generatedAt', clock_timestamp()
  );
exception when others then
  update public.stock_sync_state
  set status = 'error',
      last_error = 'v19_ranking_snapshot_refresh_failed',
      updated_at = clock_timestamp()
  where job_key = 'v19_rankings';
  raise;
end;
$$;

revoke all on function public.twss_v19_refresh_available_rankings()
  from public, anon, authenticated;
grant execute on function public.twss_v19_refresh_available_rankings()
  to service_role;

do $$
begin
  perform public.twss_v19_refresh_available_rankings();
exception when others then
  raise warning 'v19_initial_snapshot_refresh_failed';
end
$$;

do $$
declare
  existing_job bigint;
begin
  for existing_job in
    select jobid from cron.job where jobname = 'twss-v19-ranking-snapshots'
  loop
    perform cron.unschedule(existing_job);
  end loop;
end
$$;

select cron.schedule(
  'twss-v19-ranking-snapshots',
  '*/5 0-15 * * 1-5',
  $job$select public.twss_v19_refresh_available_rankings();$job$
);

do $$
declare
  existing_job bigint;
begin
  for existing_job in
    select jobid from cron.job where jobname = 'twss-v19-news'
  loop
    perform cron.unschedule(existing_job);
  end loop;
end
$$;

-- pg_cron uses UTC.  This covers 08:00-23:59 Asia/Taipei on weekdays while
-- avoiding needless overnight polling; source/external_id makes every retry
-- idempotent.
select cron.schedule(
  'twss-v19-news',
  '*/10 0-15 * * 1-5',
  $job$
    select net.http_post(
      url := 'https://lfkdkdyaatdlizryiyon.supabase.co/functions/v1/twss-v19-news',
      headers := jsonb_build_object(
        'Content-Type', 'application/json',
        'x-twss-sync-token', (
          select decrypted_secret
          from vault.decrypted_secrets
          where name = 'twss_sync_token'
        )
      ),
      body := '{}'::jsonb,
      timeout_milliseconds := 120000
    );
  $job$
);

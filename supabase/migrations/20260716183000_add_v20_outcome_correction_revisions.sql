-- Re-evaluate immutable outcomes when point-in-time price history is corrected.
-- The evaluator never mutates an observation: a changed observation hash appends
-- the next revision, while unchanged source data remains idempotent.

create or replace function public.twss_v20_evaluate_immutable_outcomes(
  p_as_of_date date,
  p_limit integer default 200
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_limit integer := least(greatest(coalesce(p_limit, 200), 1), 500);
  v_evaluation_cutoff timestamptz := clock_timestamp();
  v_candidate record;
  v_previous public.v20_outcome_observations%rowtype;
  v_revision integer;
  v_inserted integer := 0;
  v_initial integer := 0;
  v_revised integer := 0;
  v_unchanged integer := 0;
  v_correction_reasons text[];
  v_source_manifest jsonb;
begin
  if p_as_of_date is null or p_as_of_date > current_date then
    raise exception 'v20_invalid_outcome_as_of_date' using errcode = '22023';
  end if;

  -- One evaluator may scan revisions at a time, regardless of as-of date. The
  -- per-item lock below is deliberately identical to the manual append RPC's
  -- lock, so manual and automatic writers cannot allocate the same revision.
  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('twss-v20-immutable-outcomes-global', 0)
  );

  for v_candidate in
    with latest_observations as (
      select distinct on (o.recommendation_item_id, o.observed_horizon_days)
        o.*
      from public.v20_outcome_observations o
      order by
        o.recommendation_item_id,
        o.observed_horizon_days,
        o.revision desc,
        o.id desc
    ), group_state as (
      select
        i.run_id,
        i.model_key,
        i.horizon_days,
        i.group_name,
        min(i.signal_date) as signal_date,
        min(o.recorded_at) filter (where o.id is not null) as oldest_latest_recorded_at
      from public.v20_recommendation_items i
      join public.v20_recommendation_runs r
        on r.id = i.run_id
       and r.status = 'published'
      left join latest_observations o
        on o.recommendation_item_id = i.id
       and o.observed_horizon_days = i.horizon_days
      where i.public_visible
        and i.is_eligible
        and i.horizon_days in (2, 3, 5, 10, 20, 40)
        and i.signal_date < p_as_of_date
      group by i.run_id, i.model_key, i.horizon_days, i.group_name
    ), candidate_groups as (
      select g.*
      from group_state g
      where
        -- Initial observations are eligible only after the complete N-session
        -- path exists at this invocation's fixed cutoff.
        exists (
          select 1
          from public.v20_recommendation_items pending
          left join latest_observations existing
            on existing.recommendation_item_id = pending.id
           and existing.observed_horizon_days = pending.horizon_days
          join lateral (
            select
              count(*)::integer as session_count,
              (pg_catalog.array_agg(path.open order by path.trade_date))[1] as entry_price,
              (pg_catalog.array_agg(path.close order by path.trade_date))[pending.horizon_days]
                as exit_price
            from (
              select h.trade_date, h.open, h.close
              from public.stock_price_history h
              where h.symbol = pending.symbol
                and h.trade_date > pending.signal_date
                and h.trade_date <= p_as_of_date
                and h.updated_at <= v_evaluation_cutoff
              order by h.trade_date
              limit pending.horizon_days
            ) path
          ) maturity on
            maturity.session_count = pending.horizon_days
            and maturity.entry_price is not null
            and maturity.exit_price is not null
          where pending.run_id = g.run_id
            and pending.model_key = g.model_key
            and pending.horizon_days = g.horizon_days
            and pending.group_name = g.group_name
            and pending.public_visible
            and pending.is_eligible
            and existing.id is null
        )
        or (
          g.oldest_latest_recorded_at is not null
          and exists (
            -- A correction matters only if it belongs to a peer's first N
            -- sessions. Later sessions are intentionally excluded.
            select 1
            from public.v20_recommendation_items peer
            join lateral (
              select max(path.updated_at) as max_source_updated_at
              from (
                select h.updated_at
                from public.stock_price_history h
                where h.symbol = peer.symbol
                  and h.trade_date > peer.signal_date
                  and h.trade_date <= p_as_of_date
                  and h.updated_at <= v_evaluation_cutoff
                order by h.trade_date
                limit peer.horizon_days
              ) path
              having count(*) = peer.horizon_days
            ) changed_path on
              changed_path.max_source_updated_at > g.oldest_latest_recorded_at
            where peer.run_id = g.run_id
              and peer.model_key = g.model_key
              and peer.horizon_days = g.horizon_days
              and peer.group_name = g.group_name
              and peer.public_visible
          )
        )
      order by
        g.signal_date,
        g.run_id,
        g.model_key,
        g.horizon_days,
        g.group_name
      limit v_limit
    ), peer_paths as (
      select
        i.id as recommendation_item_id,
        i.run_id,
        i.symbol,
        i.model_key,
        i.horizon_days,
        i.group_name,
        i.industry,
        i.is_eligible,
        i.estimated_total_cost_pct,
        i.input_hash,
        i.take_profit_1,
        i.stop_loss,
        path.entry_date,
        path.entry_price,
        path.exit_date,
        path.exit_price,
        path.max_high,
        path.min_low,
        path.target_hit_date,
        path.stop_hit_date,
        path.price_sources,
        path.max_source_updated_at,
        pg_catalog.encode(
          extensions.digest(path.price_path::text, 'sha256'),
          'hex'
        ) as price_path_hash
      from candidate_groups g
      join public.v20_recommendation_items i
        on i.run_id = g.run_id
       and i.model_key = g.model_key
       and i.horizon_days = g.horizon_days
       and i.group_name = g.group_name
       and i.public_visible
      join lateral (
        select
          (pg_catalog.array_agg(p.trade_date order by p.trade_date))[1] as entry_date,
          (pg_catalog.array_agg(p.open order by p.trade_date))[1] as entry_price,
          (pg_catalog.array_agg(p.trade_date order by p.trade_date))[i.horizon_days]
            as exit_date,
          (pg_catalog.array_agg(p.close order by p.trade_date))[i.horizon_days]
            as exit_price,
          max(coalesce(p.high, p.close)) as max_high,
          min(coalesce(p.low, p.close)) as min_low,
          min(p.trade_date) filter (
            where i.take_profit_1 is not null
              and coalesce(p.high, p.close) >= i.take_profit_1
          ) as target_hit_date,
          min(p.trade_date) filter (
            where i.stop_loss is not null
              and coalesce(p.low, p.close) <= i.stop_loss
          ) as stop_hit_date,
          pg_catalog.array_agg(distinct p.source order by p.source) as price_sources,
          max(p.updated_at) as max_source_updated_at,
          pg_catalog.jsonb_agg(
            pg_catalog.jsonb_build_object(
              'tradeDate', p.trade_date,
              'open', p.open,
              'high', p.high,
              'low', p.low,
              'close', p.close,
              'source', p.source,
              'updatedAt', p.updated_at
            ) order by p.trade_date
          ) as price_path
        from (
          select
            h.trade_date,
            h.open,
            h.high,
            h.low,
            h.close,
            h.source,
            h.updated_at
          from public.stock_price_history h
          where h.symbol = i.symbol
            and h.trade_date > i.signal_date
            and h.trade_date <= p_as_of_date
            and h.updated_at <= v_evaluation_cutoff
          order by h.trade_date
          limit i.horizon_days
        ) p
        having count(*) = i.horizon_days
          and (pg_catalog.array_agg(p.open order by p.trade_date))[1] is not null
          and (pg_catalog.array_agg(p.close order by p.trade_date))[i.horizon_days] is not null
      ) path on true
    ), peer_returns as (
      select
        p.*,
        pg_catalog.round((100 * ((p.exit_price / p.entry_price) - 1))::numeric, 6)
          as gross_return,
        pg_catalog.round(
          (100 * ((p.exit_price / p.entry_price) - 1) - p.estimated_total_cost_pct)::numeric,
          6
        ) as net_return,
        pg_catalog.round((100 * ((p.max_high / p.entry_price) - 1))::numeric, 6) as mfe,
        pg_catalog.round((100 * ((p.min_low / p.entry_price) - 1))::numeric, 6) as mae
      from peer_paths p
    ), group_metrics as (
      select
        p.run_id,
        p.model_key,
        p.horizon_days,
        p.group_name,
        count(*)::integer as peer_count,
        avg(p.net_return) as benchmark_return,
        max(p.max_source_updated_at) as max_source_updated_at,
        pg_catalog.encode(
          extensions.digest(
            pg_catalog.jsonb_agg(
              pg_catalog.jsonb_build_object(
                'symbol', p.symbol,
                'netReturn', p.net_return,
                'pricePathHash', p.price_path_hash
              ) order by p.symbol
            )::text,
            'sha256'
          ),
          'hex'
        ) as benchmark_hash
      from peer_returns p
      group by p.run_id, p.model_key, p.horizon_days, p.group_name
    ), industry_metrics as (
      select
        p.run_id,
        p.model_key,
        p.horizon_days,
        p.group_name,
        pg_catalog.lower(coalesce(p.industry, '')) as industry_key,
        count(*)::integer as peer_count,
        avg(p.net_return) as benchmark_return,
        max(p.max_source_updated_at) as max_source_updated_at,
        pg_catalog.encode(
          extensions.digest(
            pg_catalog.jsonb_agg(
              pg_catalog.jsonb_build_object(
                'symbol', p.symbol,
                'netReturn', p.net_return,
                'pricePathHash', p.price_path_hash
              ) order by p.symbol
            )::text,
            'sha256'
          ),
          'hex'
        ) as benchmark_hash
      from peer_returns p
      group by
        p.run_id,
        p.model_key,
        p.horizon_days,
        p.group_name,
        pg_catalog.lower(coalesce(p.industry, ''))
    ), evaluated as (
      select
        p.*,
        g.peer_count as group_peer_count,
        pg_catalog.round(g.benchmark_return::numeric, 6) as group_benchmark_return,
        g.max_source_updated_at as group_max_source_updated_at,
        g.benchmark_hash as group_benchmark_hash,
        coalesce(ind.peer_count, 0) as industry_peer_count,
        case when ind.peer_count >= 5
          then pg_catalog.round(ind.benchmark_return::numeric, 6)
          else null
        end as industry_benchmark_return,
        case when ind.peer_count >= 5 then ind.max_source_updated_at else null end
          as industry_max_source_updated_at,
        case when ind.peer_count >= 5 then ind.benchmark_hash else null end
          as industry_benchmark_hash,
        case p.group_name
          when 'listed' then 'TWSE_EQUAL_WEIGHT_NET'
          when 'otc' then 'TPEX_EQUAL_WEIGHT_NET'
          when 'etf' then 'ETF_EQUAL_WEIGHT_NET'
        end as benchmark_key,
        case
          when nullif(pg_catalog.btrim(coalesce(p.industry, '')), '') is not null
            and ind.peer_count >= 5
          then 'INDUSTRY_EQUAL_WEIGHT_NET:' || pg_catalog.lower(p.industry)
          else null
        end as industry_benchmark_key,
        case
          when p.target_hit_date is null then false
          when p.stop_hit_date is null then true
          when p.target_hit_date < p.stop_hit_date then true
          when p.target_hit_date > p.stop_hit_date then false
          else null
        end as target_hit_first
      from peer_returns p
      join group_metrics g
        on g.run_id = p.run_id
       and g.model_key = p.model_key
       and g.horizon_days = p.horizon_days
       and g.group_name = p.group_name
      left join industry_metrics ind
        on ind.run_id = p.run_id
       and ind.model_key = p.model_key
       and ind.horizon_days = p.horizon_days
       and ind.group_name = p.group_name
       and ind.industry_key = pg_catalog.lower(coalesce(p.industry, ''))
      where p.is_eligible
        and g.peer_count >= 5
    ), sourced as (
      select
        e.*,
        pg_catalog.encode(
          extensions.digest(
            pg_catalog.jsonb_build_object(
              'sourceRuleVersion', 'stock-price-history-correction-v2',
              'recommendationItemId', e.recommendation_item_id,
              'horizonDays', e.horizon_days,
              'pricePathHash', e.price_path_hash,
              'groupBenchmarkHash', e.group_benchmark_hash,
              'industryBenchmarkHash', e.industry_benchmark_hash
            )::text,
            'sha256'
          ),
          'hex'
        ) as source_hash
      from evaluated e
    ), finalized as (
      select
        s.*,
        pg_catalog.encode(
          extensions.digest(
            pg_catalog.jsonb_build_object(
              'recommendationItemId', s.recommendation_item_id,
              'inputHash', s.input_hash,
              'horizonDays', s.horizon_days,
              'sourceHash', s.source_hash,
              'grossReturn', s.gross_return,
              'transactionCost', s.estimated_total_cost_pct,
              'netReturn', s.net_return,
              'benchmarkReturn', s.group_benchmark_return,
              'industryReturn', s.industry_benchmark_return,
              'mfe', s.mfe,
              'mae', s.mae,
              'targetHitFirst', s.target_hit_first
            )::text,
            'sha256'
          ),
          'hex'
        ) as observation_hash
      from sourced s
    )
    select f.*
    from finalized f
    left join latest_observations latest
      on latest.recommendation_item_id = f.recommendation_item_id
     and latest.observed_horizon_days = f.horizon_days
    where latest.observation_hash is distinct from f.observation_hash
    order by
      (latest.id is null) desc,
      f.entry_date,
      f.run_id,
      f.model_key,
      f.horizon_days,
      f.recommendation_item_id
    limit v_limit
  loop
    -- Shared with twss_v20_append_outcome_observation(jsonb).
    perform pg_catalog.pg_advisory_xact_lock(
      pg_catalog.hashtextextended(
        'twss-v20-outcome:'
          || v_candidate.recommendation_item_id::text
          || ':'
          || v_candidate.horizon_days::text,
        0
      )
    );

    select o.*
    into v_previous
    from public.v20_outcome_observations o
    where o.recommendation_item_id = v_candidate.recommendation_item_id
      and o.observed_horizon_days = v_candidate.horizon_days
    order by o.revision desc, o.id desc
    limit 1;

    if found and v_previous.observation_hash = v_candidate.observation_hash then
      v_unchanged := v_unchanged + 1;
      continue;
    end if;

    v_revision := coalesce(v_previous.revision, 0) + 1;
    v_correction_reasons := array[]::text[];

    if v_previous.id is null then
      v_correction_reasons := pg_catalog.array_append(
        v_correction_reasons,
        'initial_observation'
      );
    else
      if
        (
          nullif(v_previous.source_manifest ->> 'pricePathHash', '') is not null
          and nullif(v_previous.source_manifest ->> 'pricePathHash', '')
            is distinct from v_candidate.price_path_hash
        )
        or v_previous.entry_date is distinct from v_candidate.entry_date
        or v_previous.entry_price is distinct from v_candidate.entry_price
        or v_previous.exit_date is distinct from v_candidate.exit_date
        or v_previous.exit_price is distinct from v_candidate.exit_price
        or v_previous.mfe is distinct from v_candidate.mfe
        or v_previous.mae is distinct from v_candidate.mae
        or v_previous.target_hit_first is distinct from v_candidate.target_hit_first
      then
        v_correction_reasons := pg_catalog.array_append(
          v_correction_reasons,
          'target_price_history_revised'
        );
      end if;

      if
        (
          nullif(v_previous.source_manifest #>> '{groupBenchmark,hash}', '') is not null
          and nullif(v_previous.source_manifest #>> '{groupBenchmark,hash}', '')
            is distinct from v_candidate.group_benchmark_hash
        )
        or v_previous.benchmark_return is distinct from v_candidate.group_benchmark_return
      then
        v_correction_reasons := pg_catalog.array_append(
          v_correction_reasons,
          'group_peer_benchmark_revised'
        );
      end if;

      if
        (
          nullif(v_previous.source_manifest #>> '{industryBenchmark,hash}', '') is not null
          and nullif(v_previous.source_manifest #>> '{industryBenchmark,hash}', '')
            is distinct from v_candidate.industry_benchmark_hash
        )
        or v_previous.industry_return is distinct from v_candidate.industry_benchmark_return
      then
        v_correction_reasons := pg_catalog.array_append(
          v_correction_reasons,
          'industry_peer_benchmark_revised'
        );
      end if;

      if pg_catalog.cardinality(v_correction_reasons) = 0 then
        v_correction_reasons := pg_catalog.array_append(
          v_correction_reasons,
          'source_observation_recomputed'
        );
      end if;
    end if;

    v_source_manifest := pg_catalog.jsonb_build_object(
      'evaluationAsOfDate', p_as_of_date,
      'evaluationCutoffAt', v_evaluation_cutoff,
      'priceTable', 'stock_price_history',
      'priceSources', v_candidate.price_sources,
      'pricePathHash', v_candidate.price_path_hash,
      'priceMaxUpdatedAt', v_candidate.max_source_updated_at,
      'entryRule', 'next_session_open',
      'exitRule', 'nth_session_close',
      'horizonDays', v_candidate.horizon_days,
      'groupBenchmark', pg_catalog.jsonb_build_object(
        'key', v_candidate.benchmark_key,
        'method', 'equal_weight_net_after_item_cost',
        'peerCount', v_candidate.group_peer_count,
        'maxSourceUpdatedAt', v_candidate.group_max_source_updated_at,
        'hash', v_candidate.group_benchmark_hash
      ),
      'industryBenchmark', case
        when v_candidate.industry_peer_count >= 5 then pg_catalog.jsonb_build_object(
          'key', v_candidate.industry_benchmark_key,
          'method', 'equal_weight_net_after_item_cost',
          'peerCount', v_candidate.industry_peer_count,
          'maxSourceUpdatedAt', v_candidate.industry_max_source_updated_at,
          'hash', v_candidate.industry_benchmark_hash
        )
        else null
      end,
      'recommendationInputHash', v_candidate.input_hash,
      'previousObservation', case
        when v_previous.id is null then null
        else pg_catalog.jsonb_build_object(
          'observationId', v_previous.id,
          'revision', v_previous.revision,
          'observationHash', v_previous.observation_hash,
          'sourceHash', v_previous.source_hash,
          'recordedAt', v_previous.recorded_at
        )
      end,
      'previousObservationHash', v_previous.observation_hash,
      'previousSourceHash', v_previous.source_hash,
      'correctionReason', pg_catalog.array_to_string(v_correction_reasons, '+'),
      'correctionReasons', pg_catalog.to_jsonb(v_correction_reasons)
    );

    insert into public.v20_outcome_observations (
      recommendation_item_id,
      observed_horizon_days,
      revision,
      entry_date,
      entry_price,
      exit_date,
      exit_price,
      gross_return,
      transaction_cost,
      net_return,
      benchmark_key,
      benchmark_return,
      industry_benchmark_key,
      industry_return,
      excess_return_net,
      industry_excess_return_net,
      mfe,
      mae,
      target_hit_first,
      source_version,
      source_hash,
      source_manifest,
      observation_hash,
      observed_at,
      recorded_at
    ) values (
      v_candidate.recommendation_item_id,
      v_candidate.horizon_days,
      v_revision,
      v_candidate.entry_date,
      v_candidate.entry_price,
      v_candidate.exit_date,
      v_candidate.exit_price,
      v_candidate.gross_return,
      v_candidate.estimated_total_cost_pct,
      v_candidate.net_return,
      v_candidate.benchmark_key,
      v_candidate.group_benchmark_return,
      v_candidate.industry_benchmark_key,
      v_candidate.industry_benchmark_return,
      pg_catalog.round(
        (v_candidate.net_return - v_candidate.group_benchmark_return)::numeric,
        6
      ),
      case
        when v_candidate.industry_peer_count >= 5 then pg_catalog.round(
          (v_candidate.net_return - v_candidate.industry_benchmark_return)::numeric,
          6
        )
        else null
      end,
      v_candidate.mfe,
      v_candidate.mae,
      v_candidate.target_hit_first,
      'stock_price_history-v2-correction-aware',
      v_candidate.source_hash,
      v_source_manifest,
      v_candidate.observation_hash,
      v_evaluation_cutoff,
      clock_timestamp()
    );

    v_inserted := v_inserted + 1;
    if v_revision = 1 then
      v_initial := v_initial + 1;
    else
      v_revised := v_revised + 1;
    end if;
  end loop;

  return pg_catalog.jsonb_build_object(
    'asOfDate', p_as_of_date,
    'evaluationCutoffAt', v_evaluation_cutoff,
    'limit', v_limit,
    'inserted', v_inserted,
    'initialObservations', v_initial,
    'revisions', v_revised,
    'unchangedAfterLock', v_unchanged,
    'source', 'immutable_forward_observations',
    'sourceVersion', 'stock_price_history-v2-correction-aware',
    'entryRule', 'next_session_open',
    'exitRule', 'nth_session_close',
    'evaluatedAt', clock_timestamp()
  );
end;
$$;

revoke all on function public.twss_v20_evaluate_immutable_outcomes(date, integer)
  from public, anon, authenticated;
grant execute on function public.twss_v20_evaluate_immutable_outcomes(date, integer)
  to service_role;

comment on function public.twss_v20_evaluate_immutable_outcomes(date, integer) is
  'Service-only correction-aware evaluator. It fixes one timestamp cutoff per invocation, reads only each peer first N sessions at or before that cutoff, shares per-item advisory locks with manual append, and appends a revision only when the latest observation hash changes.';

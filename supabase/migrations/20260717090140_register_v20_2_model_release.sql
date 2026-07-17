-- Register the correctness-only v20.2 rules patch and preserve v20.1 as the
-- immediate rollback candidate. This is a structural release, not a claim of
-- forward performance; calibrated probabilities remain gated by sample count.
do $$
declare
  v_model_key text;
  v_release_id bigint;
begin
  foreach v_model_key in array array['short'::text, 'medium'::text]
  loop
    v_release_id := public.twss_v20_register_model_release(
      pg_catalog.jsonb_build_object(
        'modelKey', v_model_key,
        'modelVersion', '20.2',
        'artifactHash', '826aaac7d18c42f0733dedfee2d8b889dbf53977ca917c397d1f0feb10486061',
        'featureVersion', 'v20.2-separated-engines',
        'costModelVersion', 'tw-market-cost-2026-07',
        'validationStatus', 'passed',
        'configuration', pg_catalog.jsonb_build_object(
          'engine', 'transparent_rule_correctness_patch',
          'publicHorizons', case
            when v_model_key = 'short' then pg_catalog.to_jsonb(array[2, 3, 5, 10])
            else pg_catalog.to_jsonb(array[10, 20, 40])
          end,
          'researchHorizons', case
            when v_model_key = 'medium' then pg_catalog.to_jsonb(array[60])
            else '[]'::jsonb
          end,
          'turnoverBaseline', 'prior_20_market_sessions_minimum_5',
          'officialConfidenceRecomputed', true,
          'taifexSessionAware', true
        ),
        'validationMetrics', pg_catalog.jsonb_build_object(
          'validationKind', 'correctness_regression',
          'structuralStatus', 'passed',
          'performanceStatus', 'collecting',
          'performanceMetricsAvailable', false,
          'sampleCount', 0,
          'minimumSampleCount', 100,
          'regressionSuites', pg_catalog.to_jsonb(array[
            'v20-models', 'v20-worker', 'v20-api', 'v20-immutable-sql'
          ])
        ),
        'validationNotes',
          'Correctness repair only: restores turnover weight, recomputes official confidence and isolates TAIFEX sessions. No performance claim.',
        'registeredBy', 'migration:20260717090140'
      )
    );

    perform public.twss_v20_set_model_channel(
      pg_catalog.jsonb_build_object(
        'modelKey', v_model_key,
        'channel', 'challenger',
        'releaseId', v_release_id,
        'reason', 'Stage the v20.2 correctness patch before atomic promotion.',
        'changedBy', 'migration:20260717090140'
      )
    );

    perform public.twss_v20_promote_challenger(
      pg_catalog.jsonb_build_object(
        'modelKey', v_model_key,
        'reason', 'Promote the structurally verified v20.2 correctness patch; retain v20.1 for immediate rollback while forward performance collects.',
        'changedBy', 'migration:20260717090140'
      )
    );
  end loop;
end
$$;

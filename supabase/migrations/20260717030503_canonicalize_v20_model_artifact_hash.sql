-- Git stores deployable source files with LF line endings. Register that
-- canonical bundle identity so Windows and Linux produce the same release.
-- Existing releases remain intact for historical publication provenance.
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
        'modelVersion', '20.1',
        'artifactHash', '441cc454b03e7d689b1c5f7df71420afd7ec49ad60960286d9e349f19e286689',
        'featureVersion', 'v20.1-separated-engines',
        'costModelVersion', 'tw-market-cost-2026-07',
        'validationStatus', 'passed',
        'configuration', pg_catalog.jsonb_build_object(
          'engine', 'transparent_rule_baseline',
          'publicHorizons', case
            when v_model_key = 'short' then pg_catalog.to_jsonb(array[2, 3, 5, 10])
            else pg_catalog.to_jsonb(array[10, 20, 40])
          end,
          'researchHorizons', case
            when v_model_key = 'medium' then pg_catalog.to_jsonb(array[60])
            else '[]'::jsonb
          end
        ),
        'validationMetrics', pg_catalog.jsonb_build_object(
          'validationKind', 'structural_baseline',
          'structuralStatus', 'passed',
          'performanceStatus', 'collecting',
          'performanceMetricsAvailable', false,
          'sampleCount', 0,
          'minimumSampleCount', 100
        ),
        'validationNotes',
          'Canonical LF bundle identity; forward performance remains collecting.',
        'registeredBy', 'migration:20260717030503'
      )
    );

    perform public.twss_v20_set_model_channel(
      pg_catalog.jsonb_build_object(
        'modelKey', v_model_key,
        'channel', 'champion',
        'releaseId', v_release_id,
        'reason', 'Canonicalize the model bundle identity across operating systems.',
        'changedBy', 'migration:20260717030503'
      )
    );
  end loop;
end
$$;

import {
  MEDIUM_HORIZONS,
  MEDIUM_RESEARCH_HORIZONS,
  SHORT_HORIZONS,
  V20_MODEL_VERSION,
} from "./v20-opportunity-policy.js";

function object(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

export function buildV20PublicationManifests(input = {}) {
  const dataDate = String(input.dataDate || "").slice(0, 10);
  const sourceDates = Object.fromEntries(
    Object.entries(object(input.sourceDates))
      .filter(([, value]) => /^\d{4}-\d{2}-\d{2}/.test(String(value || "")))
      .map(([key, value]) => [key, String(value).slice(0, 10)]),
  );
  if (!/^\d{4}-\d{2}-\d{2}$/.test(dataDate) || Object.keys(sourceDates).length === 0) {
    throw new Error("v20_publication_sources_required");
  }

  return {
    sourceManifest: {
      pipeline: "stock-analysis-cache-v20",
      dataDate,
      dataCutoffAt: input.dataCutoffAt || null,
      sources: {
        analysisCache: { dataDate, groupDates: sourceDates },
        universe: { dataDate: sourceDates.universe || dataDate },
        marketContext: {
          dataDate: String(input.marketContext?.data_date || dataDate).slice(0, 10),
          available: Boolean(input.marketContext),
        },
      },
      sourceDates,
      completionKeys: input.completionKeys || [],
      groupCounts: object(input.groupCounts),
      enrichment: object(input.enrichment),
    },
    modelManifest: {
      short: {
        modelVersion: V20_MODEL_VERSION,
        engine: "transparent-rule-cost-risk-adjusted",
        horizons: [...SHORT_HORIZONS],
      },
      medium: {
        modelVersion: V20_MODEL_VERSION,
        engine: "transparent-rule-cost-risk-adjusted",
        publicHorizons: [...MEDIUM_HORIZONS],
        researchHorizons: [...MEDIUM_RESEARCH_HORIZONS],
      },
      probabilityPolicy: "walk-forward-calibrated-only-otherwise-null",
    },
  };
}
